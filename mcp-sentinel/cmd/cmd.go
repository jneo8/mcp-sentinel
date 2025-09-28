package main

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"

	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/config"
	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/entity"
	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/mcp"
	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/sentinel"
	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/watcher"
	"github.com/rs/zerolog"
	"github.com/rs/zerolog/log"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

var cfg config.Config

func init() {
	rootCmd.Flags().Bool("debug", false, "Enable debug mode")
	rootCmd.Flags().Bool("verbose", false, "Enable verbose output")
	rootCmd.Flags().StringP("config", "c", "", "Path to config file (YAML)")
	rootCmd.Flags().String("log-level", "info", "Log level (debug, info, warn, error)")
}

var rootCmd = &cobra.Command{
	Use:               config.AppName,
	RunE:              run,
	Short:             "MCP Sentinel - A Model Context Protocol client",
	PersistentPreRunE: persistentPreRun,
}

func run(cmd *cobra.Command, args []string) error {
	// Setup logging
	setupLogging()

	log.Info().
		Str("version", config.Version).
		Str("app", config.AppName).
		Msg("Starting MCP Sentinel")

	// Create context with cancellation
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	// Create watchers from config
	watchers, err := watcher.CreateWatchersFromConfig(cfg)
	if err != nil {
		return fmt.Errorf("failed to create watchers: %w", err)
	}

	// Create incident cards from config
	incidentCards, err := createIncidentCardsFromConfig(cfg)
	if err != nil {
		return fmt.Errorf("failed to create incident cards: %w", err)
	}

	// Create and initialize MCP server manager
	mcpManager := mcp.NewMCPServerManager()
	if err := mcpManager.InitializeFromConfig(ctx, cfg); err != nil {
		return fmt.Errorf("failed to initialize MCP servers: %w", err)
	}
	defer mcpManager.StopAllServers()

	// Create and start sentinel
	sentinelSvc, err := sentinel.GetSentinel(watchers, incidentCards, mcpManager, cfg)
	if err != nil {
		return fmt.Errorf("failed to create sentinel: %w", err)
	}

	log.Info().
		Int("watchers", len(watchers)).
		Int("incidentCards", len(incidentCards)).
		Int("mcpServers", len(cfg.MCPServers)).
		Msg("Starting sentinel")
	sentinelSvc.Run(ctx)

	log.Info().Msg("MCP Sentinel stopped")
	return nil
}

func setupLogging() {
	// Set log level
	switch cfg.LogLevel {
	case "debug":
		zerolog.SetGlobalLevel(zerolog.DebugLevel)
	case "info":
		zerolog.SetGlobalLevel(zerolog.InfoLevel)
	case "warn":
		zerolog.SetGlobalLevel(zerolog.WarnLevel)
	case "error":
		zerolog.SetGlobalLevel(zerolog.ErrorLevel)
	default:
		zerolog.SetGlobalLevel(zerolog.InfoLevel)
	}

	// Configure console output
	if cfg.Debug {
		log.Logger = log.Output(zerolog.ConsoleWriter{Out: os.Stderr})
	}
}

func persistentPreRun(cmd *cobra.Command, args []string) error {
	viper.SetEnvPrefix(config.EnvPrefix)
	viper.SetEnvKeyReplacer(strings.NewReplacer("-", "_"))
	viper.AutomaticEnv()

	// Explicitly bind environment variables that might not be in config file
	viper.BindEnv("openai-api-key")

	// Load config file if specified
	configFile, _ := cmd.Flags().GetString("config")
	if configFile != "" {
		viper.SetConfigFile(configFile)
		if err := viper.ReadInConfig(); err != nil {
			return fmt.Errorf("unable to read config file: %w", err)
		}
		log.Info().Str("configFile", configFile).Msg("Loaded config file")
	}

	if err := viper.BindPFlags(cmd.Flags()); err != nil {
		return fmt.Errorf("unable to bind flags: %w", err)
	}

	if err := viper.Unmarshal(&cfg); err != nil {
		return fmt.Errorf("unable to decode config: %w", err)
	}

	cfg.SetDefaults()
	if err := cfg.Validate(); err != nil {
		return fmt.Errorf("config validation failed: %w", err)
	}
	return nil
}

func createIncidentCardsFromConfig(cfg config.Config) ([]entity.IncidentCard, error) {
	var incidentCards []entity.IncidentCard

	for _, cardConfig := range cfg.IncidentCards {
		// Convert string tools to McpTool structs
		var tools []entity.McpTool
		for _, toolStr := range cardConfig.Tools {
			// Parse "server-name.tool-name" format
			parts := strings.Split(toolStr, ".")
			if len(parts) == 2 {
				tools = append(tools, entity.McpTool{
					ServerName: parts[0],
					ToolName:   parts[1],
				})
			}
		}

		// Determine max iterations: use card-specific value or global default
		maxIterations := cardConfig.MaxIterations
		if maxIterations == 0 {
			maxIterations = cfg.DefaultMaxIterations
		}

		card := entity.IncidentCard{
			Resource: entity.Resource{
				Name: cardConfig.Resource, // Bind to resource name
			},
			Prompt:        cardConfig.Prompt,
			Tools:         tools,
			MaxIterations: maxIterations,
		}
		incidentCards = append(incidentCards, card)
	}

	return incidentCards, nil
}

func Execute() {
	if err := rootCmd.Execute(); err != nil {
		os.Exit(1)
	}
}
