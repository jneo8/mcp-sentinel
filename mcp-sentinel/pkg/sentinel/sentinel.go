package sentinel

import (
	"context"
	"fmt"
	"sync"

	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/entity"
	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/watcher"
	"github.com/rs/zerolog/log"
)

type Sentinel interface {
	Run(ctx context.Context)
}

func GetSentinel(watchers []watcher.Watcher, incidentCards []entity.IncidentCard) (Sentinel, error) {
	return &sentinel{
		watchers:      watchers,
		incidentCards: incidentCards,
	}, nil
}

type sentinel struct {
	watchers      []watcher.Watcher
	incidentCards []entity.IncidentCard
}

func (s *sentinel) Run(ctx context.Context) {
	var wg sync.WaitGroup
	notificationCh := make(chan entity.Notification, 100)

	// Start all watchers in separate goroutines
	for i, w := range s.watchers {
		wg.Add(1)
		go func(watcherID int, watcher watcher.Watcher) {
			defer wg.Done()
			log.Info().Int("watcherID", watcherID).Msg("Starting watcher")
			watcher.Run(ctx, notificationCh)
		}(i, w)
	}

	// Start notification processor with injected IncidentCards
	go s.processNotifications(ctx, notificationCh)

	// Wait for context cancellation
	<-ctx.Done()
	log.Info().Msg("Sentinel shutting down")

	// Close notification channel and wait for watchers
	close(notificationCh)
	wg.Wait()
}

func (s *sentinel) processNotifications(ctx context.Context, notificationCh <-chan entity.Notification) {
	for {
		select {
		case notification, ok := <-notificationCh:
			if !ok {
				return
			}
			s.handleNotification(notification)
		case <-ctx.Done():
			return
		}
	}
}

func (s *sentinel) handleNotification(notification entity.Notification) {
	// Find matching IncidentCard or use the first one
	var selectedCard *entity.IncidentCard
	if len(s.incidentCards) > 0 {
		selectedCard = &s.incidentCards[0] // TODO: Add logic to select appropriate card
	} else {
		log.Error().Msg("No incident cards available")
		return
	}

	// Bind notification to IncidentCard
	selectedCard.Resource = notification.Resource
	selectedCard.Prompt = s.generatePrompt(notification)

	// Print the prompt and log the incident
	log.Warn().
		Interface("resource", selectedCard.Resource).
		Str("prompt", selectedCard.Prompt).
		Msg("INCIDENT DETECTED")
}

func (s *sentinel) generatePrompt(notification entity.Notification) string {
	return fmt.Sprintf("Alert: Resource change detected - %+v", notification.Resource)
}
