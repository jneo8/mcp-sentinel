"""MCP server for Juju exec commands - Ceph troubleshooting tools."""

import signal
import sys

import click
from fastmcp import FastMCP
from jubilant import Juju
from loguru import logger


mcp = FastMCP("mcp-juju")
juju = Juju()


def run_juju_exec(unit: str, command: str) -> dict:
    """Execute command on Juju unit using jubilant."""
    logger.info(f"Executing command on unit {unit}: {command}")
    try:
        task = juju.exec(command, unit=unit)
        logger.info(f"Command completed with status: {task.status}, return_code: {task.return_code}")
        return {
            "success": True,
            "unit": unit,
            "command": command,
            "stdout": task.stdout,
            "stderr": task.stderr,
            "return_code": task.return_code,
            "status": task.status,
        }
    except Exception as e:
        logger.error(f"Error executing command on {unit}: {e}")
        return {
            "success": False,
            "unit": unit,
            "command": command,
            "error": str(e),
        }


@mcp.tool()
def ceph_health_detail(unit: str = "ceph-mon/0") -> str:
    """Get detailed Ceph cluster health status via juju exec.

    Args:
        unit: Juju unit name (default: ceph-mon/0)

    Returns:
        Detailed Ceph health status
    """
    logger.info(f"Tool called: ceph_health_detail with unit={unit}")
    result = run_juju_exec(unit, "sudo ceph health detail")

    if result["success"]:
        return f"Command: {result['command']}\nUnit: {result['unit']}\nReturn Code: {result['return_code']}\n\nOutput:\n{result['stdout']}"
    else:
        return f"Error: {result['error']}"


@mcp.tool()
def ceph_osd_tree(unit: str = "ceph-mon/0") -> str:
    """Get Ceph OSD tree topology showing which OSDs are up/down.

    Args:
        unit: Juju unit name (default: ceph-mon/0)

    Returns:
        Ceph OSD tree topology
    """
    logger.info(f"Tool called: ceph_osd_tree with unit={unit}")
    result = run_juju_exec(unit, "sudo ceph osd tree")

    if result["success"]:
        return f"Command: {result['command']}\nUnit: {result['unit']}\nReturn Code: {result['return_code']}\n\nOutput:\n{result['stdout']}"
    else:
        return f"Error: {result['error']}"


@mcp.tool()
def ceph_osd_status(unit: str = "ceph-mon/0") -> str:
    """Get current status of all Ceph OSDs (up/down, in/out).

    Args:
        unit: Juju unit name (default: ceph-mon/0)

    Returns:
        Current OSD status
    """
    logger.info(f"Tool called: ceph_osd_status with unit={unit}")
    result = run_juju_exec(unit, "sudo ceph osd stat")

    if result["success"]:
        return f"Command: {result['command']}\nUnit: {result['unit']}\nReturn Code: {result['return_code']}\n\nOutput:\n{result['stdout']}"
    else:
        return f"Error: {result['error']}"


@mcp.tool()
def ceph_osd_df(unit: str = "ceph-mon/0") -> str:
    """Get Ceph OSD disk usage statistics.

    Args:
        unit: Juju unit name (default: ceph-mon/0)

    Returns:
        OSD disk usage information
    """
    logger.info(f"Tool called: ceph_osd_df with unit={unit}")
    result = run_juju_exec(unit, "sudo ceph osd df")

    if result["success"]:
        return f"Command: {result['command']}\nUnit: {result['unit']}\nReturn Code: {result['return_code']}\n\nOutput:\n{result['stdout']}"
    else:
        return f"Error: {result['error']}"


@mcp.tool()
def juju_exec(unit: str, command: str) -> str:
    """Execute arbitrary command on a Juju unit.

    Args:
        unit: Juju unit name (e.g., 'ceph-mon/0')
        command: Command to execute

    Returns:
        Command execution output
    """
    logger.info(f"Tool called: juju_exec with unit={unit}, command={command}")
    result = run_juju_exec(unit, command)

    if result["success"]:
        output = f"Command: {result['command']}\nUnit: {result['unit']}\nReturn Code: {result['return_code']}\n\n"
        if result['stdout']:
            output += f"Output:\n{result['stdout']}\n"
        if result['stderr']:
            output += f"Stderr:\n{result['stderr']}\n"
        return output
    else:
        return f"Error: {result['error']}"


@click.command()
@click.option(
    "--host",
    default="0.0.0.0",
    help="Host to bind the server to",
    show_default=True,
)
@click.option(
    "--port",
    default=8000,
    type=int,
    help="Port to bind the server to",
    show_default=True,
)
@click.option(
    "--log-level",
    default="INFO",
    type=click.Choice(["DEBUG", "INFO", "WARNING", "ERROR"], case_sensitive=False),
    help="Logging level",
    show_default=True,
)
def main(host: str, port: int, log_level: str):
    """MCP Juju server - Execute Juju commands for Ceph troubleshooting."""
    # Configure logger level
    logger.remove()
    logger.add(sys.stderr, level=log_level.upper())

    def signal_handler(sig, frame):
        logger.info("Server stopped by user")
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        logger.info(f"Starting MCP Juju server on http://{host}:{port}")
        mcp.run(transport="streamable-http", host=host, port=port)
    except KeyboardInterrupt:
        logger.info("Server stopped")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise


if __name__ == "__main__":
    main()
