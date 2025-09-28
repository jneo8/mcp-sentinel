package watcher

import (
	"context"

	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/entity"
)

type Watcher interface {
	Run(ctx context.Context, notificationCh chan<- entity.Notification)
}
