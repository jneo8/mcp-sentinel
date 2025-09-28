package config

type Config struct {
	// Basic CLI flags
	Debug   bool
	Verbose bool

	// Configuration file path
	ConfigFile string `mapstructure:"config-file"`

	// Log level
	LogLevel string `mapstructure:"log-level"`

	// OpenAI configuration
	OpenAIAPIKey         string `mapstructure:"openai-api-key"`
	OpenAIModel          string `mapstructure:"openai-model"`
	OpenAIURL            string `mapstructure:"openai-url"`
	DefaultMaxIterations int    `mapstructure:"default-max-iterations"`

	// Resources - Single source of truth
	Resources []ResourceConfig `mapstructure:"resources"`

	// Watchers configuration
	Watchers []WatcherConfig `mapstructure:"watchers"`

	// MCP Servers configuration
	MCPServers []MCPServerConfig `mapstructure:"mcp-servers"`

	// Incident Cards configuration
	IncidentCards []IncidentCardConfig `mapstructure:"incident-cards"`
}

type ResourceConfig struct {
	Name    string         `mapstructure:"name"`
	Type    string         `mapstructure:"type"`
	Filters map[string]any `mapstructure:"filters"`
}

type WatcherConfig struct {
	Type         string   `mapstructure:"type"`
	Name         string   `mapstructure:"name"`
	Endpoint     string   `mapstructure:"endpoint"`
	PollInterval string   `mapstructure:"poll-interval"`
	Resources    []string `mapstructure:"resources"`
}

type MCPServerConfig struct {
	Name string `mapstructure:"name"`
	Type string `mapstructure:"type"` // "stdio" or "streamable"

	// For stdio servers
	Command string   `mapstructure:"command"`
	Args    []string `mapstructure:"args"`
	WorkDir string   `mapstructure:"work-dir"`

	// For streamable HTTP servers
	URL string `mapstructure:"url"`

	// Common settings
	Timeout   string            `mapstructure:"timeout"`
	Env       map[string]string `mapstructure:"env"`
	AutoStart bool              `mapstructure:"auto-start"`
	Tools     []string          `mapstructure:"tools"` // Available tools on this server
}

type IncidentCardConfig struct {
	Name          string   `mapstructure:"name"`
	Resource      string   `mapstructure:"resource"`
	Prompt        string   `mapstructure:"prompt"`
	Tools         []string `mapstructure:"tools"`          // Format: "server-name.tool-name"
	MaxIterations int      `mapstructure:"max-iterations"` // Maximum LLM conversation iterations
}

func (c *Config) Validate() error {
	return nil
}

func (c *Config) SetDefaults() {
	if c.LogLevel == "" {
		c.LogLevel = "info"
	}
	if c.OpenAIModel == "" {
		c.OpenAIModel = "gpt-4o"
	}
	if c.DefaultMaxIterations == 0 {
		c.DefaultMaxIterations = 10
	}
}
