// main.go
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	openai "github.com/openai/openai-go/v2"
	"github.com/openai/openai-go/v2/option"

	"github.com/mark3labs/mcp-go/client"
	"github.com/mark3labs/mcp-go/mcp"
)

func main() {
	// ---- Config (env) ----
	// OpenAI (or OpenAI-compatible) configs
	baseURL := getenvDefault("BASE_URL", "https://api.openai.com/v1") // point to OpenAI, LiteLLM, OpenRouter, vLLM, Ollama...
	apiKey := os.Getenv("OPENAI_API_KEY")                             // for local engines, "dummy" often works
	if apiKey == "" && !strings.Contains(baseURL, "localhost") {
		log.Fatal("Set OPENAI_API_KEY (or run against a local OpenAI-compatible endpoint).")
	}
	model := getenvDefault("MODEL", "gpt-4o-mini")

	// MCP server configs - use a general filesystem MCP server for POC
	stdioCmd := getenvDefault("MCP_STDIO_CMD", "npx")
	stdioArgs := []string{"@modelcontextprotocol/server-filesystem", "./tmp-test"}
	if envArgs := os.Getenv("MCP_STDIO_ARGS"); envArgs != "" {
		stdioArgs = splitNonEmpty(envArgs)
	}

	// ---- OpenAI client ----
	oa := openai.NewClient(
		option.WithBaseURL(baseURL),
		option.WithAPIKey(apiKey),
	)

	// ---- Context & signals ----
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	// ---- Create MCP client (stdio) ----
	serverName := "filesystem-server"
	mcpClient, err := client.NewStdioMCPClient(stdioCmd, nil, stdioArgs...)
	if err != nil {
		log.Fatalf("stdio create: %v", err)
	}

	// ---- Start & Initialize MCP ----
	if err := mcpClient.Start(ctx); err != nil {
		log.Fatalf("[%s] start: %v", serverName, err)
	}
	defer mcpClient.Close()

	initReq := mcp.InitializeRequest{
		Params: mcp.InitializeParams{
			ProtocolVersion: "2024-11-05",
			Capabilities: mcp.ClientCapabilities{
				Roots: &struct {
					ListChanged bool `json:"listChanged,omitempty"`
				}{ListChanged: true},
				Sampling:    &struct{}{},
				Elicitation: &struct{}{},
			},
			ClientInfo: mcp.Implementation{Name: "mcp-hello-openai", Version: "0.1.0"},
		},
	}
	ctxInit, cancelInit := context.WithTimeout(ctx, 10*time.Second)
	defer cancelInit()
	if _, err := mcpClient.Initialize(ctxInit, initReq); err != nil {
		log.Fatalf("[%s] initialize: %v", serverName, err)
	}
	if err := mcpClient.Ping(ctx); err != nil {
		log.Fatalf("[%s] ping: %v", serverName, err)
	}
	fmt.Printf("[%s] Connected & ping OK\n", serverName)

	// ---- Get available tools and let LLM choose which ones to use ----
	toolsRes, err := mcpClient.ListTools(ctx, mcp.ListToolsRequest{})
	if err != nil {
		log.Fatalf("list tools: %v", err)
	}

	// Build tools description for LLM
	var toolsDesc strings.Builder
	toolsDesc.WriteString("Available MCP tools:\n")
	for _, tool := range toolsRes.Tools {
		toolsDesc.WriteString(fmt.Sprintf("- %s: %s\n", tool.Name, tool.Description))
		// Note: InputSchema structure varies, so we'll keep it simple for now
		toolsDesc.WriteString("  (Check tool documentation for parameters)\n")
	}

	// User query that requires tool selection
	userQuery := getenvDefault("USER_QUERY", "Can you check what files are in the tmp-test directory and read the content of any text files you find?")

	// Ask LLM to analyze the query and decide which tools to use
	systemPrompt := fmt.Sprintf(`You are an AI assistant with access to MCP (Model Context Protocol) tools.
Your task is to analyze the user's request and decide which tools to use and in what order.

%s

User Request: %s

Please respond with a JSON array of tool calls you want to make. Each tool call should have:
- "tool": the tool name
- "args": object with the tool arguments

Example format:
[
  {"tool": "list_directory", "args": {"path": "."}},
  {"tool": "read_file", "args": {"path": "README.md"}}
]

Only respond with the JSON array, no other text.`, toolsDesc.String(), userQuery)

	resp, err := oa.Chat.Completions.New(ctx, openai.ChatCompletionNewParams{
		Model: openai.ChatModel(model),
		Messages: []openai.ChatCompletionMessageParamUnion{
			openai.SystemMessage(systemPrompt),
		},
	})
	if err != nil {
		log.Fatalf("LLM request failed: %v", err)
	}

	llmResponse := resp.Choices[0].Message.Content
	fmt.Printf("LLM planned tool calls: %s\n\n", llmResponse)

	// Parse and execute the tool calls
	var toolCalls []struct {
		Tool string         `json:"tool"`
		Args map[string]any `json:"args"`
	}

	if err := json.Unmarshal([]byte(llmResponse), &toolCalls); err != nil {
		log.Fatalf("Failed to parse LLM response: %v", err)
	}

	// Execute each tool call
	var results []map[string]any
	for i, toolCall := range toolCalls {
		fmt.Printf("Executing tool %d: %s\n", i+1, toolCall.Tool)

		callReq := mcp.CallToolRequest{
			Params: mcp.CallToolParams{
				Name:      toolCall.Tool,
				Arguments: toolCall.Args,
			},
		}

		res, err := mcpClient.CallTool(ctx, callReq)
		if err != nil {
			fmt.Printf("Tool call failed: %v\n", err)
			continue
		}

		pretty := map[string]any{}
		raw, _ := json.Marshal(res)
		_ = json.Unmarshal(raw, &pretty)

		result := map[string]any{
			"tool":   toolCall.Tool,
			"args":   toolCall.Args,
			"result": pretty,
		}
		results = append(results, result)

		fmt.Printf("Result: %s\n\n", string(raw))
	}

	// Final summary
	finalSummary(ctx, oa, model, userQuery, results)
}

func finalSummary(ctx context.Context, oa openai.Client, model string, userQuery string, results []map[string]any) {
	fmt.Println("\n== Final Summary ==")

	resultsJson, _ := json.MarshalIndent(results, "", "  ")

	summaryPrompt := fmt.Sprintf(`Please provide a comprehensive summary of this MCP interaction session:

Original User Request: %s

Tool Execution Results: %s

Please summarize:
1. What the user requested
2. Which tools were selected and why
3. The outcome of each tool execution
4. Overall success/failure and key findings
5. Any insights or recommendations

Provide a clear, concise summary for a human operator.`, userQuery, string(resultsJson))

	resp, err := oa.Chat.Completions.New(ctx, openai.ChatCompletionNewParams{
		Model: openai.ChatModel(model),
		Messages: []openai.ChatCompletionMessageParamUnion{
			openai.UserMessage(summaryPrompt),
		},
	})

	if err != nil || len(resp.Choices) == 0 {
		fmt.Printf("(summary failed: %v)\n", err)
		return
	}

	fmt.Println(resp.Choices[0].Message.Content)
}

func splitNonEmpty(s string) []string {
	if s == "" {
		return nil
	}
	parts := strings.Split(s, ",")
	out := make([]string, 0, len(parts))
	for _, p := range parts {
		if p = strings.TrimSpace(p); p != "" {
			out = append(out, p)
		}
	}
	return out
}

func joinToolNames(tools []mcp.Tool) string {
	names := make([]string, 0, len(tools))
	for _, t := range tools {
		names = append(names, t.Name)
	}
	return strings.Join(names, ", ")
}

func getenvDefault(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}
