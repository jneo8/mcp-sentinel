package config

type Config struct {
	// Basic CLI flags
	Debug   bool
	Verbose bool

	// Configuration file path
	ConfigFile string `mapstructure:"config-file"`

	// Log level
	LogLevel string `mapstructure:"log-level"`
}

func (c *Config) Validate() error {
	return nil
}

func (c *Config) SetDefaults() {
	if c.LogLevel == "" {
		c.LogLevel = "info"
	}
}