package watcher

import (
	"fmt"
	"time"

	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/config"
)

// CreateWatchersFromConfig creates watchers based on configuration
func CreateWatchersFromConfig(cfg config.Config) ([]Watcher, error) {
	var watchers []Watcher

	// Create resource map for quick lookup
	resourceMap := make(map[string]config.ResourceConfig)
	for _, resource := range cfg.Resources {
		resourceMap[resource.Name] = resource
	}

	for _, watcherConfig := range cfg.Watchers {
		switch watcherConfig.Type {
		case "prometheus":
			// Parse poll interval
			pollInterval, err := time.ParseDuration(watcherConfig.PollInterval)
			if err != nil {
				return nil, fmt.Errorf("invalid poll interval for watcher %s: %w", watcherConfig.Name, err)
			}

			// Build resource configs for this watcher
			resourceConfigs := make(map[string]config.ResourceConfig)
			for _, resourceName := range watcherConfig.Resources {
				if resource, exists := resourceMap[resourceName]; exists {
					resourceConfigs[resourceName] = resource
				} else {
					return nil, fmt.Errorf("resource %s not found for watcher %s", resourceName, watcherConfig.Name)
				}
			}

			// Create Prometheus watcher
			w := NewPrometheusWatcher(
				watcherConfig.Name,
				watcherConfig.Endpoint,
				pollInterval,
				resourceConfigs,
			)
			watchers = append(watchers, w)

		default:
			return nil, fmt.Errorf("unknown watcher type: %s", watcherConfig.Type)
		}
	}

	return watchers, nil
}