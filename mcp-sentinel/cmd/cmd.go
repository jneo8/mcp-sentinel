package main

import (
	"fmt"
	"os"
	"sync"

	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/config"
	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/sentinel"
	"github.com/juju/juju/core/watcher"
	"github.com/spf13/cobra"
	"github.com/spf13/viper"
)

var cfg config.Config

func init() {
	rootCmd.Flags().Bool("debug", false, "Enable debug mode")
	rootCmd.Flags().Bool("verbose", false, "Enable verbose output")
	rootCmd.Flags().String("config-file", "", "Config file path")
	rootCmd.Flags().String("log-level", "info", "Log level (debug, info, warn, error)")
}

var rootCmd = &cobra.Command{
	Use:               config.AppName,
	RunE:              run,
	Short:             "MCP Sentinel - A Model Context Protocol client",
	PersistentPreRunE: persistentPreRun,
}

func run(cmd *cobra.Command, args []string) error {
	stopChan := make(chan struct{})
	wg := sync.WaitGroup{}

	sentinelSvc := sentinel.GetSentinel([]watcher.Watcher{})
	return nil
}

func persistentPreRun(cmd *cobra.Command, args []string) error {
	viper.AutomaticEnv()
	viper.SetEnvPrefix(config.EnvPrefix)
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

func Execute() {
	if err := rootCmd.Execute(); err != nil {
		os.Exit(1)
	}
}
