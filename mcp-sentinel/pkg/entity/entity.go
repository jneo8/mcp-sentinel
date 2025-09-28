package entity

import (
	"crypto/sha256"
	"fmt"
	"sort"
	"strings"
)

type McpTool struct {
	ServerName string
	ToolName   string
}

type IncidentCard struct {
	Resource      Resource
	Prompt        string
	Tools         []McpTool
	MaxIterations int
}

type Resource struct {
	Type        string            `json:"type"`
	Name        string            `json:"name"`
	Labels      map[string]string `json:"labels,omitempty"`
	Annotations map[string]string `json:"annotations,omitempty"`
	State       string            `json:"state,omitempty"`
	Value       string            `json:"value,omitempty"`
	Timestamp   string            `json:"timestamp,omitempty"`
}

// ID generates a unique identifier for the resource based on its type, name, labels, and timestamp
// This is used for deduplication to prevent processing the same alert multiple times
func (r *Resource) ID() string {
	h := sha256.New()

	// Include type and name which are the primary identifiers
	h.Write([]byte(r.Type))
	h.Write([]byte("|"))
	h.Write([]byte(r.Name))

	// Include labels in a consistent order for deterministic hashing
	if len(r.Labels) > 0 {
		h.Write([]byte("|"))

		// Sort labels by key for consistent ordering
		var labelPairs []string
		for k, v := range r.Labels {
			labelPairs = append(labelPairs, fmt.Sprintf("%s=%s", k, v))
		}
		sort.Strings(labelPairs)

		h.Write([]byte(strings.Join(labelPairs, ",")))
	}

	// Include timestamp for unique identification
	if r.Timestamp != "" {
		h.Write([]byte("|"))
		h.Write([]byte(r.Timestamp))
	}

	return fmt.Sprintf("%x", h.Sum(nil))
}

type Notification struct {
	Resource Resource
}
