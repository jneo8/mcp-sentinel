package entity

type McpTool struct{}

type IncidentCard struct {
	Resource Resource
	Prompt   string
	Tools    []McpTool
}

type Resource struct{}

type Notification struct {
	Resource Resource
}
