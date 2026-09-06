import asyncio
import os
from typing import Optional, List, Dict, Any, Tuple
from contextlib import AsyncExitStack
import json

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
# Using Quasar Alpha as specified in requirements.md
LLM_MODEL = "openai/gpt-4.1"

class MCPClient:
    def __init__(self):
        self.session: Optional[ClientSession] = None
        self.exit_stack = AsyncExitStack()
        self.openai_client = OpenAI(
            base_url=OPENROUTER_BASE_URL,
            api_key=OPENROUTER_API_KEY,
        )
        self.available_tools_schema = []
        self.model_name = LLM_MODEL
        self.github_token = os.getenv("GITHUB_PERSONAL_ACCESS_TOKEN")
        if not self.github_token:
            raise ValueError("GITHUB_PERSONAL_ACCESS_TOKEN is not set in environment.")

    async def connect_to_server(self):
        """Connect to GitHub MCP server via docker stdio."""
        docker_cmd = [
            "docker", "run", "-i", "--rm",
            "-e", f"GITHUB_PERSONAL_ACCESS_TOKEN={self.github_token}",
            "ghcr.io/github/github-mcp-server"
        ]

        server_params = StdioServerParameters(
            command=docker_cmd[0],
            args=docker_cmd[1:],
            env=os.environ.copy()
        )

        try:
            stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
            self.stdio, self.write = stdio_transport
            self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))

            await self.session.initialize()

            response = await self.session.list_tools()
            self.available_tools_schema = [{
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.inputSchema
                }
            } for tool in response.tools]
            print(f"Connected to GitHub MCP server. Available tools: {[tool['function']['name'] for tool in self.available_tools_schema]}")

        except Exception as e:
            print(f"Error connecting to MCP server: {e}")
            raise

    async def analyze_conversation(self, messages: List[Dict[str, Any]]) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Analyze a conversation to determine if a tool call should be made, but don't execute it.
        
        Args:
            messages: A list of message objects compatible with the OpenAI API format.
            
        Returns:
            Tuple containing:
            - bool: Whether a tool call was suggested
            - Optional[Dict]: Tool call information if suggested, otherwise None
        """
        if not self.session:
            print("Error: MCPClient is not connected to the server.")
            return False, None
        if not self.available_tools_schema:
            print("Error: No tools available from the MCP server.")
            return False, None

        try:
            # Add a system prompt to guide the LLM
            system_prompt = """
            You are an AI assistant integrated into a Discord chat. Your goal is to monitor the conversation
            and determine if a GitHub issue needs to be created based on the discussion.
            Use the available 'create_issue' tool if you identify a clear problem, bug report,
            feature request, or actionable task that should be tracked on GitHub.
            Only call the tool if you are confident an issue is warranted. Include relevant details
            from the conversation in the issue title, body and labels. Ensure the owner and repo are correct.
            If no issue is needed, do not call any tools.
            Ensure the issue language is in English.
            The target repository owner is 'jimmyhealer' and the repo is 'vocora'.
            """
            processed_messages = [{"role": "system", "content": system_prompt}] + messages

            print(f"Sending conversation to LLM ({self.model_name}):")

            chat_completion = self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=processed_messages,
                tools=self.available_tools_schema,
                tool_choice="auto", # Let the model decide if a tool call is needed
            )

            response_message = chat_completion.choices[0].message

            # Check if the LLM decided to call a tool
            if response_message.tool_calls:
                print("LLM suggested tool call:")
                tool_call = response_message.tool_calls[0]  # Get the first tool call
                function_name = tool_call.function.name
                function_args = json.loads(tool_call.function.arguments)

                # Ensure owner and repo are set, potentially overriding LLM's choice if needed
                if 'owner' not in function_args:
                    function_args['owner'] = 'jimmyhealer'  # Default owner
                    print(f"Injecting default owner: 'jimmyhealer'")
                if 'repo' not in function_args:
                    function_args['repo'] = 'vocora'  # Default repo
                    print(f"Injecting default repo: 'vocora'")

                print(f"- Tool: {function_name}")
                print(f"- Arguments: {function_args}")
                
                # Return suggested tool call but don't execute it
                return True, {
                    "tool_name": function_name,
                    "arguments": function_args,
                }
            else:
                print("LLM decided no tool call is needed.")
                return False, None

        except Exception as e:
            print(f"Error during LLM interaction: {e}")
            return False, None
            
    async def execute_tool_call(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a tool call with the given arguments.
        
        Args:
            tool_name: The name of the tool to call
            arguments: The arguments to pass to the tool
            
        Returns:
            Dict containing either the result or error information
        """
        if not self.session:
            return {"error": "MCPClient is not connected to the server."}
            
        try:
            print(f"Executing tool '{tool_name}' via MCP server...")
            result = await self.session.call_tool(tool_name, arguments)
            print(f"Tool '{tool_name}' executed successfully.")
            print(f"Tool Result Content: {result.content}")
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "result": result.content
            }
        except Exception as e:
            print(f"Error calling tool '{tool_name}' via MCP: {e}")
            return {
                "tool_name": tool_name,
                "arguments": arguments,
                "error": str(e)
            }

    async def process_conversation(self, messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Legacy method for backward compatibility.
        Processes a conversation and executes any tool calls immediately.
        
        DEPRECATED: Use analyze_conversation and execute_tool_call instead.
        """
        suggested, tool_info = await self.analyze_conversation(messages)
        if suggested and tool_info:
            return await self.execute_tool_call(tool_info["tool_name"], tool_info["arguments"])
        return None

    async def cleanup(self):
        """Clean up resources."""
        print("Cleaning up MCPClient resources...")
        await self.exit_stack.aclose()
        print("MCPClient cleanup complete.")

# Example usage (for testing purposes)
async def _test_mcp_client():
    print("Testing MCPClient...")
    client = MCPClient()
    try:
        await client.connect_to_server()

        # Simulate a conversation that might lead to an issue
        test_messages = [
            {"role": "user", "content": "Hey team, I think I found a bug."},
            {"role": "user", "content": "When I click the 'Submit' button without filling out the form, the page crashes."},
            {"role": "assistant", "content": "Oh, that sounds serious. Can you provide more details?"},
            {"role": "user", "content": "Yeah, it throws a JavaScript error in the console. Looks like a null reference."},
            {"role": "user", "content": "We should probably track this."},
        ]

        suggested, tool_info = await client.analyze_conversation(test_messages)
        
        if suggested and tool_info:
            print(f"Test successful: Tool '{tool_info['tool_name']}' suggested.")
            print(f"Arguments: {tool_info['arguments']}")
            
            # Example of executing the suggested tool call
            result = await client.execute_tool_call(tool_info["tool_name"], tool_info["arguments"])
            if 'error' not in result:
                print(f"Tool execution successful.")
                print(f"Result Content: {result['result']}")
            else:
                print(f"Tool execution failed with error: {result['error']}")
        else:
            print("Test Info: No tool call was suggested by the LLM.")

    except Exception as e:
         print(f"Test failed with exception: {e}")
    finally:
        await client.cleanup()

if __name__ == "__main__":
    # To run this test:
    # 1. Ensure you have a .env file with OPENROUTER_API_KEY and MCP_GITHUB_SERVER_PATH
    # 2. Make sure the GitHub MCP server script is available at the specified path and executable.
    # 3. Run `python mcp_client.py`
    asyncio.run(_test_mcp_client())
    print("MCPClient defined. Run this file directly only for testing (_test_mcp_client function).") 