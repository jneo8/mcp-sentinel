# Troubleshooting Ceph OSD Failures with MCP Sentinel

In this tutorial, you'll learn how to use MCP Sentinel to automatically investigate Ceph storage issues. By the end, you'll have MCP Sentinel detecting OSD failures and using Juju to gather diagnostic information.

## Video Walkthrough

Watch this complete demonstration of the tutorial steps:

[![asciicast](https://asciinema.org/a/746727.svg)](https://asciinema.org/a/746727)

## What you'll build

You'll create an automated incident response system that:
- Monitors Prometheus for CephOSDDownHigh alerts
- Automatically investigates OSD failures using Juju exec commands
- Generates intelligent summaries with remediation recommendations

## Before you start

You'll need:
- A Juju-managed Ceph cluster deployment (this tutorial uses [MicroCeph](https://ubuntu.com/ceph/microceph))
- [COS Lite](https://charmhub.io/topics/canonical-observability-stack) integrated with your Ceph cluster for monitoring
- Juju CLI access to the controller and model
- An OpenAI API key
- Python 3.11+ with `uv` installed

## Getting your environment ready

First, let's set up your credentials and verify Juju access:

```bash
# Set your OpenAI API key
export OPENAI_API_KEY=your-api-key-here

# Verify you can access your Juju environment
juju status
```

If the status output appears showing your Ceph deployment, you're ready to continue.

## Step 1: Start the Juju MCP server

MCP Sentinel needs the Juju MCP server to execute Ceph diagnostic commands. Start it:

```bash
cd mcp_servers/mcp_juju
make run
```

You should see output indicating the server is listening:
```
INFO Starting MCP Juju server on http://0.0.0.0:8000
```

Keep this terminal open.

## Step 2: Create a problem to investigate

To simulate a CephOSDDownHigh alert, we'll manually kill a ceph-osd process in the MicroCeph cluster. This tutorial assumes you have MicroCeph integrated with COS Lite for monitoring.

```bash
# First, check which MicroCeph units you have
juju status microceph

# Pick a unit and find running OSD processes
juju ssh microceph/0 -- ps aux | grep ceph-osd

# You should see output like:
# root      123456  ... /usr/bin/ceph-osd -f --cluster ceph --id 1 ...
# root      123457  ... /usr/bin/ceph-osd -f --cluster ceph --id 2 ...

# Kill one of the ceph-osd processes (adjust PID and OSD ID as needed)
juju ssh microceph/0 -- sudo kill -9 <PID>

# For example, to kill OSD 1:
juju ssh microceph/0 -- 'sudo pkill -9 -f "ceph-osd.*--id 1"'

# Verify the OSD is down by checking from any microceph unit
juju ssh microceph/0 -- sudo ceph osd tree
```

You should see one OSD marked as "down" in the output. After a few minutes (typically 5-10 minutes depending on your Prometheus scrape interval and alert rules), this will trigger the CephOSDDownHigh alert in Prometheus.

## Step 3: Configure MCP Sentinel

Create a configuration file for the Ceph troubleshooting scenario:

```bash
cat > config-ceph.yaml <<'EOF'
# MCP Sentinel Configuration - Ceph OSD Troubleshooting
debug: true
log-level: debug

# MCP Servers - External services for incident response
mcp-servers:
  - name: juju-mcp
    server-url: "http://localhost:8000/mcp"
    default-allowed-tools:
      - juju_status
      - juju_units
      - ceph_health_detail
      - ceph_osd_tree
      - ceph_osd_status
      - ceph_osd_df
      - juju_exec

# Resources - Single source of truth
resources:
  - name: ceph-osd-down-high
    type: prometheus_alert
    filters:
      alertname: "CephOSDDownHigh"

# Watchers - Produce notifications for specific resources
watchers:
  - type: prometheus
    name: ceph-prometheus
    endpoint: "http://your-prometheus-endpoint/api/v1"
    poll-interval: "10s"
    resources:
      - ceph-osd-down-high

# Incident Cards - Listen to specific resources
incident-cards:
  - name: ceph-osd-down-investigation
    resource: ceph-osd-down-high
    max-iterations: 15
    prompt: |
      CEPH OSD DOWN ALERT INVESTIGATION:
      Alert: ${resource_name}
      Resource: ${resource_type}
      State: ${resource_state}
      Labels: ${resource_labels}

      GOAL: Investigate Ceph OSD failures and provide diagnostic information for remediation.

      CONTEXT:
      - The CephOSDDownHigh alert fires when multiple OSDs are down in the cluster
      - OSDs can be down due to: service failures, disk failures, network issues, or configuration problems
      - Ceph requires a minimum number of OSDs to maintain data availability

      REQUIRED INVESTIGATION STEPS:
      1. Use juju-mcp.juju_status to discover available Ceph applications in the deployment
      2. Use juju-mcp.juju_units with the appropriate Ceph application names (e.g., 'ceph-mon', 'ceph-osd', 'microceph') to get exact unit names
      3. Use juju-mcp.ceph_health_detail with a valid Ceph monitor unit to get overall cluster health status
      4. Use juju-mcp.ceph_osd_tree with a valid Ceph monitor unit to see the cluster topology and identify which OSDs are down
      5. Use juju-mcp.ceph_osd_status with a valid Ceph monitor unit to get current OSD statistics (how many up/down, in/out)
      6. Use juju-mcp.ceph_osd_df with a valid Ceph monitor unit to check disk usage patterns before failure
      7. Use juju-mcp.juju_exec to check systemd service status on affected OSD units
      8. Use juju-mcp.juju_exec to check recent logs for failed OSDs

      ANALYSIS REQUIREMENTS:
      - Identify which specific OSDs are down (by ID and host)
      - Determine if OSDs are down due to service failure or other causes
      - Check if there are any warning signs in cluster health
      - Assess impact on data availability (degraded PGs, etc.)

      OUTPUT FORMAT:
      Provide a concise incident summary with:
      1. **Alert Details**: What triggered the alert
      2. **Affected OSDs**: List of down OSDs with their hosts
      3. **Cluster Health**: Current Ceph health status
      4. **Root Cause Analysis**: Why the OSDs are down (based on evidence)
      5. **Impact Assessment**: Effect on cluster performance and data availability
      6. **Remediation Steps**: Specific actions to resolve the issue

      Execute the investigation systematically and provide evidence-based recommendations.
    tools:
      - juju-mcp.juju_status
      - juju-mcp.juju_units
      - juju-mcp.ceph_health_detail
      - juju-mcp.ceph_osd_tree
      - juju-mcp.ceph_osd_status
      - juju-mcp.ceph_osd_df
      - juju-mcp.juju_exec
EOF
```

**Important**: Update the `endpoint` value in the watchers section to match your Prometheus server.

## Step 4: Run MCP Sentinel

Now start MCP Sentinel in a new terminal:

```bash
# Make sure your OpenAI key is available
export OPENAI_API_KEY=your-api-key-here

# Start MCP Sentinel
uv run python -m mcp_sentinel --config config-ceph.yaml run
```

You should see logs indicating:
- MCP Sentinel is starting
- The Prometheus watcher is polling
- Connection to the Juju MCP server is established

## Step 5: Watch the investigation

MCP Sentinel will now:

1. **Detect** the CephOSDDownHigh alert
2. **Trigger** the incident response workflow
3. **Investigate** using Juju commands:
   - Discover available Ceph applications with `juju_status`
   - Get unit names with `juju_units`
   - Check Ceph cluster health details
   - List OSD topology to identify down OSDs
   - Get OSD statistics
   - Check disk usage patterns
   - Investigate systemd service status
   - Review recent logs for errors
4. **Generate** a comprehensive incident summary

In the logs, look for:

```
INFO Starting agent run card=ceph-osd-down-investigation
INFO Connected to MCP server server_name=juju-mcp
INFO Agent run completed - Final Output:
```

The agent's final output will explain why OSDs are down and suggest remediation steps.

## Example Incident Card Output

Here's what a successful investigation might look like:

```
**Incident Summary:**

1. **Alert Details:**
   - Alert "CephOSDDownHigh" fired due to 1 out of 3 OSDs (33.33%) being down, specifically osd.1 on host juju-d6f34a-9.

2. **Affected OSDs:**
   - osd.1 on host juju-d6f34a-9 is down.
   - Two other OSDs (osd.2 and osd.3) on the same host are up.

3. **Cluster Health:**
   - Ceph cluster reports HEALTH_WARN status.
   - 1 OSD down (osd.1).
   - Data redundancy degraded with 2/6 objects degraded and 1 PG degraded and undersized.
   - PG 1.0 is stuck in active+undersized+degraded state.

4. **Root Cause Analysis:**
   - OSD.1 is down as reported by the cluster and confirmed by OSD tree and OSD status.
   - `ceph-osd` service process for osd.1 is not running on microceph/8 (the unit related to juju-d6f34a-9).
   - There's no systemd service file for ceph-osd@1 found on the unit, suggesting possible misconfiguration or failure to start OSD instance.
   - Other osd services for OSD 2 and 3 are running properly (processes visible).
   - No recent journal logs for ceph-osd@1 indicating it may never have started or was removed.

5. **Impact Assessment:**
   - Loss of one OSD has led to degraded data redundancy.
   - PG under-replication and degradation observed.
   - Potential risk to data availability if further OSDs fail before recovery.

6. **Remediation Steps:**
   - Investigate the state and configuration of OSD.1 on juju-d6f34a-9.
   - Confirm if the OSD daemon for osd.1 is configured to run and enabled as a service or managed another way.
   - Attempt to start or restart OSD.1 service or pod if containerized.
   - Check for any underlying disk or device issues related to OSD.1.
   - Review deployment or charm configuration that manages OSD instances to ensure osd.1 is properly deployed.
   - Monitor cluster health after recovery steps to validate OSD.1 is up and data redundancy improves.
```

## What you should see

A successful investigation will show the agent discovered:
- Exact OSDs that are down (ID and host)
- Current cluster health status
- Whether the issue is service-related or hardware-related
- Impact on data availability
- Specific commands to remediate

## Clean up

When you're done exploring:

```bash
# The killed ceph-osd process should automatically restart via systemd or the charm
# If not, you can manually restart it:
juju ssh microceph/0 -- sudo systemctl restart microceph

# Verify cluster is healthy
juju ssh microceph/0 -- sudo ceph -s

# Wait until cluster shows HEALTH_OK and all OSDs are up

# Stop MCP Sentinel (Ctrl+C in its terminal)
# Stop the Juju MCP server (Ctrl+C in its terminal)

# Remove the test configuration
rm config-ceph.yaml
```

## What you learned

You've successfully:
- Set up MCP Sentinel with Juju integration
- Created a Ceph OSD failure scenario
- Observed automated investigation using Ceph commands
- Seen AI-generated root cause analysis and remediation steps
- Used the mcp_juju server to execute Juju commands remotely

## What's next

Now that you understand Ceph troubleshooting with MCP Sentinel, you can:
- Create incident cards for other Ceph alerts (CephPoolFull, CephSlowOps, etc.)
- Add additional diagnostic tools to the Juju MCP server
- Integrate with your incident management system (PagerDuty, Opsgenie)
- Set up automated remediation for common issues
- Create runbooks based on investigation patterns

## Troubleshooting

**"No alerts detected"**: Update the Prometheus endpoint in `config-ceph.yaml` to match your environment.

**"Connection failed to MCP server"**: Ensure the Juju MCP server is running on port 8000.

**"Juju command failed"**: Verify your Juju client can access the controller and model.

**"Permission denied on ceph commands"**: Ensure the Juju user has sudo permissions on Ceph units.

**"Agent produces no output"**: Check that your OpenAI API key is valid and has sufficient credits.
