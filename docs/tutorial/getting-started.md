# Getting Started with MCP Sentinel

In this tutorial, you'll learn how to use MCP Sentinel by setting up automated incident response for Kubernetes pod alerts. By the end, you'll have MCP Sentinel automatically detecting and investigating pod readiness issues.

## Video Walkthrough

Watch this complete demonstration of the tutorial steps:

[![asciicast](https://asciinema.org/a/746726.svg)](https://asciinema.org/a/746726)

## What you'll build

You'll create a complete incident response system that:
- Monitors Prometheus for Kubernetes pod alerts
- Automatically investigates pod issues using Kubernetes tools
- Generates intelligent summaries and remediation suggestions

## Before you start

You'll need:
- A Kubernetes cluster with `kubectl` access
- An OpenAI API key
- Python 3.11+ with `uv` and `uvx` installed

## Getting your environment ready

First, let's set up your credentials and verify cluster access:

```bash
# Set your OpenAI API key
export OPENAI_API_KEY=your-api-key-here

# Verify you can access your Kubernetes cluster
kubectl cluster-info
```

If the cluster info appears, you're ready to continue.

## Step 1: Start the Kubernetes tools

MCP Sentinel needs external tools to investigate issues. Start the Kubernetes MCP server:

```bash
uvx kubernetes-mcp-server@latest --port 8080
```

You should see output indicating the server is listening on port 8080. Keep this terminal open.

## Step 2: Create a problem to investigate

Let's create a Kubernetes deployment that will trigger a pod readiness alert:

```bash
# Create a test namespace
kubectl create namespace workload

# Create a deployment with an impossible scheduling requirement
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: Deployment
metadata:
  name: broken-app
  namespace: workload
spec:
  replicas: 1
  selector:
    matchLabels:
      app: broken-app
  template:
    metadata:
      labels:
        app: broken-app
    spec:
      nodeSelector:
        kubernetes.io/hostname: nonexistent-node
      containers:
      - name: app
        image: registry.k8s.io/pause:3.9
EOF
```

Check that the pod is stuck in a pending state:

```bash
kubectl get pods -n workload
```

You should see a pod in `Pending` status. This is the issue MCP Sentinel will investigate.

## Step 3: Configure MCP Sentinel

The repository includes a ready-to-use configuration file at `config.yaml`. Let's examine what it does:

- **Monitors Prometheus** for `KubePodNotReady` alerts
- **Connects to the Kubernetes MCP server** you just started
- **Defines an investigation workflow** that checks pod status and related events

The configuration is already set up - you don't need to modify it for this tutorial.

## Step 4: Run MCP Sentinel

Now start MCP Sentinel in a new terminal:

```bash
# Make sure your OpenAI key is available
source .env  # if you have an .env file, or export it again

# Start MCP Sentinel
uv run python -m mcp_sentinel --config config.yaml run
```

You should see logs indicating:
- MCP Sentinel is starting
- The Prometheus watcher is polling
- Connection to the Kubernetes MCP server is established

## Step 5: Watch the investigation

MCP Sentinel will now:

1. **Detect** when the pod is not ready
2. **Trigger** the incident response workflow
3. **Investigate** using Kubernetes tools:
   - List namespaces to verify connectivity
   - Get pod details from the workload namespace
   - Check for related events
4. **Generate** a summary explaining the issue

In the logs, look for:

```
INFO Starting agent run card=kube-pod-not-ready-alert
INFO Connected to MCP server server_name=k8s-mcp
INFO Agent run completed - Final Output:
```

The agent's final output will explain why the pod isn't ready and suggest fixes.

## What you should see

A successful investigation will show the agent discovered:
- The pod is in "Pending" state
- It can't be scheduled due to the impossible node selector
- Recommendations to fix the scheduling constraint

Example output:
```
The pod 'broken-app-xxx' in namespace 'workload' cannot be scheduled
because it requires a node with hostname 'nonexistent-node' which
doesn't exist. Recommended actions: remove the nodeSelector constraint
or ensure a node with that hostname is available.
```

## Clean up

When you're done exploring:

```bash
# Remove the test deployment
kubectl delete namespace workload

# Stop MCP Sentinel (Ctrl+C in its terminal)
# Stop the Kubernetes MCP server (Ctrl+C in its terminal)
```

## What you learned

You've successfully:
- ✅ Set up MCP Sentinel with external tool integration
- ✅ Created a monitored incident scenario
- ✅ Observed automated investigation and analysis
- ✅ Seen AI-generated remediation recommendations

## What's next

Now that you understand the basics, you can:
- Modify the incident card prompt to change investigation steps
- Add more MCP servers for different types of tools
- Create incident cards for other types of alerts
- Set up production monitoring with real Prometheus alerts

## Troubleshooting

**"No alerts detected"**: The Prometheus endpoint in `config.yaml` may need updating for your environment.

**"Connection failed to MCP server"**: Ensure the Kubernetes MCP server is running on port 8080.

**"Agent produces no output"**: Check that your OpenAI API key is valid and has sufficient credits.

**"Permission denied" errors**: Verify your kubectl context has permissions to read pods and events.