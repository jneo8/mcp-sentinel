package watcher

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/config"
	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/entity"
	"github.com/rs/zerolog/log"
)

type PrometheusAlert struct {
	Labels      map[string]string `json:"labels"`
	Annotations map[string]string `json:"annotations"`
	State       string            `json:"state"`
	ActiveAt    time.Time         `json:"activeAt"`
	Value       string            `json:"value"`
}

type PrometheusResponse struct {
	Status string `json:"status"`
	Data   struct {
		Alerts []PrometheusAlert `json:"alerts"`
	} `json:"data"`
}

type PrometheusWatcher struct {
	name         string
	endpoint     string
	pollInterval time.Duration
	client       *http.Client
	resources    map[string]config.ResourceConfig // resource name -> config
}

func NewPrometheusWatcher(name, endpoint string, pollInterval time.Duration, resources map[string]config.ResourceConfig) Watcher {
	return &PrometheusWatcher{
		name:         name,
		endpoint:     endpoint,
		pollInterval: pollInterval,
		resources:    resources,
		client: &http.Client{
			Timeout: 10 * time.Second,
		},
	}
}

func (pw *PrometheusWatcher) Run(ctx context.Context, notificationCh chan<- entity.Notification) {
	log.Info().
		Str("endpoint", pw.endpoint).
		Dur("pollInterval", pw.pollInterval).
		Msg("Starting Prometheus watcher")

	ticker := time.NewTicker(pw.pollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			log.Info().Msg("Prometheus watcher shutting down")
			return
		case <-ticker.C:
			pw.checkAlerts(ctx, notificationCh)
		}
	}
}

func (pw *PrometheusWatcher) checkAlerts(ctx context.Context, notificationCh chan<- entity.Notification) {
	alertsURL := fmt.Sprintf("%s/api/v1/alerts", pw.endpoint)

	req, err := http.NewRequestWithContext(ctx, "GET", alertsURL, nil)
	if err != nil {
		log.Error().Err(err).Msg("Failed to create request")
		return
	}

	resp, err := pw.client.Do(req)
	if err != nil {
		log.Error().Err(err).Msg("Failed to fetch alerts from Prometheus")
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		log.Error().
			Int("statusCode", resp.StatusCode).
			Msg("Prometheus API returned non-200 status")
		return
	}

	var promResp PrometheusResponse
	if err := json.NewDecoder(resp.Body).Decode(&promResp); err != nil {
		log.Error().Err(err).Msg("Failed to decode Prometheus response")
		return
	}

	// Process firing alerts
	firingAlerts := pw.filterFiringAlerts(promResp.Data.Alerts)
	log.Debug().Int("firingCount", len(firingAlerts)).Msg("Found firing alerts")

	for _, alert := range firingAlerts {
		// Check if alert matches any of our resources
		for resourceName, resourceFilter := range pw.resources {
			if pw.matchesResource(alert, resourceFilter) {
				notification := pw.createNotification(alert, resourceName)

				select {
				case notificationCh <- notification:
					log.Debug().
						Str("alertname", alert.Labels["alertname"]).
						Str("resource", resourceName).
						Msg("Sent alert notification")
				case <-ctx.Done():
					return
				default:
					log.Warn().Msg("Notification channel full, dropping alert")
				}
				break // Only send one notification per alert
			}
		}
	}
}

func (pw *PrometheusWatcher) filterFiringAlerts(alerts []PrometheusAlert) []PrometheusAlert {
	var firing []PrometheusAlert
	for _, alert := range alerts {
		if alert.State == "firing" {
			firing = append(firing, alert)
		}
	}
	return firing
}

func (pw *PrometheusWatcher) matchesResource(alert PrometheusAlert, resource config.ResourceConfig) bool {
	for filterKey, filterValue := range resource.Filters {
		alertValue, exists := alert.Labels[filterKey]
		if !exists {
			return false
		}

		// Handle string values
		if strVal, ok := filterValue.(string); ok {
			if alertValue != strVal {
				return false
			}
		}

		// Handle slice values (multiple possible values)
		if sliceVal, ok := filterValue.([]interface{}); ok {
			found := false
			for _, val := range sliceVal {
				if strVal, ok := val.(string); ok && alertValue == strVal {
					found = true
					break
				}
			}
			if !found {
				return false
			}
		}
	}
	return true
}

func (pw *PrometheusWatcher) createNotification(alert PrometheusAlert, resourceName string) entity.Notification {
	alertName := alert.Labels["alertname"]
	if alertName == "" {
		alertName = "UnknownAlert"
	}

	resource := entity.Resource{
		Type:        "prometheus_alert",
		Name:        resourceName, // Use the resource name instead of alert name
		Labels:      alert.Labels,
		Annotations: alert.Annotations,
		State:       alert.State,
		Value:       alert.Value,
		Timestamp:   alert.ActiveAt.Format(time.RFC3339),
	}

	return entity.Notification{
		Resource: resource,
	}
}