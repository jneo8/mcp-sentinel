package mcp

import (
	"context"
	"fmt"
	"time"

	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/config"
	"github.com/mark3labs/mcp-go/client"
	"github.com/mark3labs/mcp-go/mcp"
	"github.com/rs/zerolog/log"
)

type MCPServer struct {
	Config config.MCPServerConfig
	Client *client.Client
}

type MCPServerManager struct {
	servers map[string]*MCPServer
}

func NewMCPServerManager() *MCPServerManager {
	return &MCPServerManager{
		servers: make(map[string]*MCPServer),
	}
}

func (m *MCPServerManager) InitializeFromConfig(ctx context.Context, cfg config.Config) error {
	for _, serverConfig := range cfg.MCPServers {
		// Only handle stdio servers for now
		if serverConfig.Type != "stdio" {
			log.Info().Str("server", serverConfig.Name).Str("type", serverConfig.Type).Msg("Skipping non-stdio server")
			continue
		}

		server := &MCPServer{
			Config: serverConfig,
		}
		m.servers[serverConfig.Name] = server

		// Start server if auto-start is enabled
		if serverConfig.AutoStart {
			if err := m.startStdioServer(ctx, server); err != nil {
				log.Error().Err(err).Str("server", serverConfig.Name).Msg("Failed to start stdio MCP server")
				return err
			}
		}
	}
	return nil
}

func (m *MCPServerManager) GetServer(name string) (*MCPServer, error) {
	server, exists := m.servers[name]
	if !exists {
		return nil, fmt.Errorf("MCP server %s not found", name)
	}
	return server, nil
}

func (m *MCPServerManager) startStdioServer(ctx context.Context, server *MCPServer) error {
	// Parse timeout
	timeout := 30 * time.Second
	if server.Config.Timeout != "" {
		if t, err := time.ParseDuration(server.Config.Timeout); err == nil {
			timeout = t
		}
	}

	// Prepare environment
	env := []string{}
	if server.Config.Env != nil {
		for k, v := range server.Config.Env {
			env = append(env, fmt.Sprintf("%s=%s", k, v))
		}
	}

	// Create stdio MCP client
	mcpClient, err := client.NewStdioMCPClient(
		server.Config.Command,
		env,
		server.Config.Args...,
	)
	if err != nil {
		return fmt.Errorf("failed to create stdio MCP client: %w", err)
	}

	server.Client = mcpClient
	log.Info().Str("server", server.Config.Name).Msg("Created MCP stdio client")

	// Initialize client with timeout
	initCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()

	initRequest := mcp.InitializeRequest{}
	initRequest.Params.ProtocolVersion = mcp.LATEST_PROTOCOL_VERSION
	initRequest.Params.ClientInfo = mcp.Implementation{
		Name:    "mcp-sentinel",
		Version: "0.0.1",
	}

	initResult, err := mcpClient.Initialize(initCtx, initRequest)
	if err != nil {
		mcpClient.Close()
		server.Client = nil
		return fmt.Errorf("failed to initialize MCP client: %w", err)
	}

	log.Info().
		Str("server", server.Config.Name).
		Str("serverName", initResult.ServerInfo.Name).
		Str("serverVersion", initResult.ServerInfo.Version).
		Msg("MCP stdio server initialized successfully")

	return nil
}

func (m *MCPServerManager) StopServer(name string) error {
	server, err := m.GetServer(name)
	if err != nil {
		return err
	}

	if server.Client != nil {
		if err := server.Client.Close(); err != nil {
			log.Warn().Err(err).Str("server", name).Msg("Failed to close MCP client")
		}
		server.Client = nil
	}

	log.Info().Str("server", name).Msg("MCP server stopped")
	return nil
}

func (m *MCPServerManager) StopAllServers() {
	for name := range m.servers {
		if err := m.StopServer(name); err != nil {
			log.Warn().Err(err).Str("server", name).Msg("Failed to stop MCP server")
		}
	}
}