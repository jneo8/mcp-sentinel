package sentinel

import (
	"context"
	"encoding/json"
	"fmt"
	"sync"

	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/config"
	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/entity"
	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/mcp"
	"github.com/jneo8/mcp-sentinel/mcp-sentinel/pkg/watcher"
	mcpLib "github.com/mark3labs/mcp-go/mcp"
	"github.com/openai/openai-go/v2"
	"github.com/openai/openai-go/v2/option"
	"github.com/openai/openai-go/v2/packages/param"
	"github.com/openai/openai-go/v2/shared"
	"github.com/rs/zerolog/log"
)

type Sentinel interface {
	Run(ctx context.Context)
}

func GetSentinel(watchers []watcher.Watcher, incidentCards []entity.IncidentCard, mcpManager *mcp.MCPServerManager, cfg config.Config) (Sentinel, error) {
	// Create OpenAI client with configuration
	var openaiClient openai.Client
	if cfg.OpenAIURL != "" {
		openaiClient = openai.NewClient(
			option.WithBaseURL(cfg.OpenAIURL),
			option.WithAPIKey(cfg.OpenAIAPIKey),
		)
	} else {
		openaiClient = openai.NewClient(
			option.WithAPIKey(cfg.OpenAIAPIKey),
		)
	}

	return &sentinel{
		watchers:        watchers,
		incidentCards:   incidentCards,
		mcpManager:      mcpManager,
		openaiClient:    openaiClient,
		config:          cfg,
		processedAlerts: make(map[string]bool),
	}, nil
}

type sentinel struct {
	watchers      []watcher.Watcher
	incidentCards []entity.IncidentCard
	mcpManager    *mcp.MCPServerManager
	openaiClient  openai.Client
	config        config.Config

	// In-memory deduplication
	processedAlerts map[string]bool
	alertsMutex     sync.RWMutex
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
	// Generate unique ID for the resource
	resourceID := notification.Resource.ID()

	// Check if this alert has already been processed
	s.alertsMutex.RLock()
	alreadyProcessed := s.processedAlerts[resourceID]
	s.alertsMutex.RUnlock()

	if alreadyProcessed {
		log.Debug().
			Str("resourceID", resourceID).
			Str("resourceName", notification.Resource.Name).
			Msg("Alert already processed, skipping duplicate")
		return
	}

	// Mark as processed
	s.alertsMutex.Lock()
	s.processedAlerts[resourceID] = true
	s.alertsMutex.Unlock()

	log.Info().
		Str("resourceID", resourceID).
		Str("resourceName", notification.Resource.Name).
		Msg("Processing new alert")

	// Find matching IncidentCard by resource name
	var selectedCard *entity.IncidentCard
	for i := range s.incidentCards {
		if s.incidentCards[i].Resource.Name == notification.Resource.Name {
			selectedCard = &s.incidentCards[i]
			break
		}
	}

	if selectedCard == nil {
		log.Warn().
			Str("resourceName", notification.Resource.Name).
			Msg("No incident card found for resource")
		return
	}

	// Update the card with notification data
	selectedCard.Resource = notification.Resource

	log.Warn().
		Interface("resource", selectedCard.Resource).
		Str("prompt", selectedCard.Prompt).
		Msg("INCIDENT DETECTED")

	// Process incident with LLM
	ctx := context.Background()
	if err := s.processIncidentWithLLM(ctx, selectedCard); err != nil {
		log.Error().Err(err).Msg("Failed to process incident with LLM")
	}
}

func (s *sentinel) processIncidentWithLLM(ctx context.Context, card *entity.IncidentCard) error {
	log.Info().
		Str("incidentCard", card.Resource.Name).
		Interface("availableTools", card.Tools).
		Msg("Processing incident with continuous LLM conversation")

	// Step 1: Discover available MCP tools and their schemas
	availableTools, err := s.discoverMCPTools(ctx, card.Tools)
	if err != nil {
		return fmt.Errorf("failed to discover MCP tools: %w", err)
	}

	// Step 2: Start continuous conversation with LLM
	return s.runContinuousLLMConversation(ctx, card, availableTools)
}

// ToolWithServer wraps an MCP tool with its server information
type ToolWithServer struct {
	mcpLib.Tool
	ServerName string
}

func (s *sentinel) discoverMCPTools(ctx context.Context, requiredTools []entity.McpTool) ([]ToolWithServer, error) {
	var availableTools []ToolWithServer

	// Group required tools by server to avoid multiple ListTools calls per server
	serverToolsMap := make(map[string][]string)
	for _, requiredTool := range requiredTools {
		serverToolsMap[requiredTool.ServerName] = append(serverToolsMap[requiredTool.ServerName], requiredTool.ToolName)
	}

	// Call ListTools once per server
	for serverName, toolNames := range serverToolsMap {
		server, err := s.mcpManager.GetServer(serverName)
		if err != nil {
			log.Warn().
				Str("serverName", serverName).
				Err(err).
				Msg("Failed to get MCP server for tool discovery")
			continue
		}

		if server.Client == nil {
			log.Warn().
				Str("serverName", serverName).
				Msg("MCP server client is not initialized")
			continue
		}

		// List tools from the server once
		log.Info().Str("serverName", serverName).Msg("Calling ListTools on MCP server")
		listToolsResp, err := server.Client.ListTools(ctx, mcpLib.ListToolsRequest{})
		if err != nil {
			log.Warn().
				Str("serverName", serverName).
				Err(err).
				Msg("Failed to list tools from MCP server")
			continue
		}

		// Find all required tools from this server
		for _, tool := range listToolsResp.Tools {
			for _, requiredToolName := range toolNames {
				if tool.Name == requiredToolName {
					availableTools = append(availableTools, ToolWithServer{
						Tool:       tool,
						ServerName: serverName,
					})
					break
				}
			}
		}
	}

	return availableTools, nil
}

func (s *sentinel) runContinuousLLMConversation(ctx context.Context, card *entity.IncidentCard, availableTools []ToolWithServer) error {
	// Create OpenAI tool definitions from MCP tool schemas
	var tools []openai.ChatCompletionToolUnionParam
	for _, tool := range availableTools {
		functionDef := shared.FunctionDefinitionParam{
			Name:        tool.Name,
			Description: openai.String(tool.Description),
		}

		// Convert MCP tool input schema to OpenAI function parameters
		if tool.InputSchema.Type != "" {
			parameters := shared.FunctionParameters{
				"type": tool.InputSchema.Type,
			}

			if tool.InputSchema.Properties != nil {
				parameters["properties"] = tool.InputSchema.Properties
			}

			if len(tool.InputSchema.Required) > 0 {
				parameters["required"] = tool.InputSchema.Required
			}

			functionDef.Parameters = parameters
		}

		tools = append(tools, openai.ChatCompletionFunctionTool(functionDef))
	}

	// Initialize conversation with system prompt and incident context
	systemPrompt := fmt.Sprintf(IncidentResponseSystemPrompt,
		card.Prompt,
		card.Resource.Name,
		card.Resource.Type,
		card.Resource.State,
		card.Resource.Value,
		card.Resource.Timestamp)

	messages := []openai.ChatCompletionMessageParamUnion{
		openai.SystemMessage(systemPrompt),
		openai.UserMessage(InitialUserPrompt),
	}

	model := openai.ChatModel(s.config.OpenAIModel)
	maxIterations := card.MaxIterations

	for iteration := 0; iteration < maxIterations; iteration++ {
		log.Info().
			Str("incidentCard", card.Resource.Name).
			Int("iteration", iteration+1).
			Msg("Sending request to LLM in continuous conversation")

		// Call LLM with function calling enabled
		params := openai.ChatCompletionNewParams{
			Model:    model,
			Messages: messages,
			Tools:    tools,
		}

		// For the first iteration, encourage tool usage
		if iteration == 0 && len(tools) > 0 {
			params.ToolChoice = openai.ChatCompletionToolChoiceOptionUnionParam{
				OfAuto: param.NewOpt(string(openai.ChatCompletionToolChoiceOptionAutoAuto)),
			}
		}

		resp, err := s.openaiClient.Chat.Completions.New(ctx, params)
		if err != nil {
			return fmt.Errorf("failed to get LLM response: %w", err)
		}

		choice := resp.Choices[0]

		log.Info().
			Str("incidentCard", card.Resource.Name).
			Int("iteration", iteration+1).
			Str("response", choice.Message.Content).
			Msg("LLM response received")

		// Check if LLM wants to call tools
		if len(choice.Message.ToolCalls) > 0 {
			// Convert tool calls to param type
			var toolCallParams []openai.ChatCompletionMessageToolCallUnionParam
			for _, toolCall := range choice.Message.ToolCalls {
				toolCallParams = append(toolCallParams, toolCall.ToParam())
			}

			// Add assistant message with tool calls to conversation
			var assistant openai.ChatCompletionAssistantMessageParam
			assistant.Content.OfString = param.NewOpt(choice.Message.Content)
			assistant.ToolCalls = toolCallParams

			messages = append(messages, openai.ChatCompletionMessageParamUnion{OfAssistant: &assistant})
			// Process each tool call
			for _, toolCall := range choice.Message.ToolCalls {
				if toolCall.Type == "function" {
					// Execute the tool call
					mcpToolCall := LLMToolCall{
						ServerName: s.findServerForTool(toolCall.Function.Name, availableTools),
						ToolName:   toolCall.Function.Name,
						Arguments:  make(map[string]any),
					}

					// Parse function arguments if provided
					if toolCall.Function.Arguments != "" {
						// Parse JSON arguments properly
						var args map[string]any
						if err := json.Unmarshal([]byte(toolCall.Function.Arguments), &args); err != nil {
							log.Error().
								Err(err).
								Str("functionName", toolCall.Function.Name).
								Str("arguments", toolCall.Function.Arguments).
								Msg("Failed to parse function arguments")
						} else {
							mcpToolCall.Arguments = args
						}

						log.Info().
							Str("functionName", toolCall.Function.Name).
							Str("arguments", toolCall.Function.Arguments).
							Msg("LLM requested function call")
					}

					// Execute the MCP tool
					result, err := s.executeMCPToolCall(ctx, mcpToolCall)
					if err != nil {
						// Add error message to conversation
						errorMsg := fmt.Sprintf("Tool call failed: %v", err)
						messages = append(messages, openai.ToolMessage(errorMsg, toolCall.ID))

						log.Error().
							Err(err).
							Interface("toolCall", mcpToolCall).
							Msg("Failed to execute MCP tool call")
						continue
					}

					// Return raw result directly to LLM
					resultText := fmt.Sprintf("%+v", result)
					messages = append(messages, openai.ToolMessage(resultText, toolCall.ID))

					// log.Info().
					// 	Interface("toolCall", mcpToolCall).
					// 	Str("result", resultText).
					// 	Msg("MCP tool executed, result added to conversation")
				}
			}

			// Continue the conversation with tool results
			continue
		}

		// No function call - LLM provided final response
		// Add assistant message to conversation for consistency
		messages = append(messages, openai.AssistantMessage(choice.Message.Content))

		log.Info().
			Str("incidentCard", card.Resource.Name).
			Str("finalResponse", choice.Message.Content).
			Msg("LLM provided final incident analysis")

		return nil
	}

	log.Warn().
		Str("incidentCard", card.Resource.Name).
		Int("maxIterations", maxIterations).
		Msg("LLM conversation reached maximum iterations")

	return nil
}

func (s *sentinel) findServerForTool(toolName string, availableTools []ToolWithServer) string {
	for _, tool := range availableTools {
		if tool.Name == toolName {
			return tool.ServerName
		}
	}
	return ""
}

func (s *sentinel) executeMCPToolCall(ctx context.Context, toolCall LLMToolCall) (*mcpLib.CallToolResult, error) {
	server, err := s.mcpManager.GetServer(toolCall.ServerName)
	if err != nil {
		return nil, fmt.Errorf("failed to get MCP server %s: %w", toolCall.ServerName, err)
	}

	if server.Client == nil {
		return nil, fmt.Errorf("MCP server %s is not connected", toolCall.ServerName)
	}

	log.Info().
		Str("serverName", toolCall.ServerName).
		Str("toolName", toolCall.ToolName).
		Interface("arguments", toolCall.Arguments).
		Msg("Executing LLM-recommended MCP tool")

	request := mcpLib.CallToolRequest{
		Params: mcpLib.CallToolParams{
			Name:      toolCall.ToolName,
			Arguments: toolCall.Arguments,
		},
	}

	log.Debug().
		Interface("request", request).
		Msg("Sending MCP tool request")

	result, err := server.Client.CallTool(ctx, request)
	if err != nil {
		log.Error().
			Err(err).
			Str("serverName", toolCall.ServerName).
			Str("toolName", toolCall.ToolName).
			Msg("MCP tool call failed")
		return nil, fmt.Errorf("failed to call MCP tool %s.%s: %w", toolCall.ServerName, toolCall.ToolName, err)
	}

	// log.Debug().
	// 	Interface("result", result).
	// 	Msg("Received MCP tool result")

	return result, nil
}

type LLMToolCall struct {
	ServerName string
	ToolName   string
	Arguments  map[string]any
}

func (s *sentinel) generatePrompt(notification entity.Notification) string {
	return fmt.Sprintf("Alert: Resource change detected - %+v", notification.Resource)
}
