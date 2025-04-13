import asyncio
import os
from typing import Optional, List, Dict, Any
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
LLM_MODEL = "openrouter/optimus-alpha"

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

    async def process_conversation(self, messages: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """
        Process a conversation history using the LLM and potentially call MCP tools.

        Args:
            messages: A list of message objects compatible with the OpenAI API format.

        Returns:
            A dictionary containing the tool call result if a tool was called, otherwise None.
        """
        if not self.session:
            print("Error: MCPClient is not connected to the server.")
            return None
        if not self.available_tools_schema:
            print("Error: No tools available from the MCP server.")
            return None

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
            The target repository owner is 'jimmyhealer' and the repo is 'vocora'.
            """
            processed_messages = [{"role": "system", "content": system_prompt}] + messages

            print(f"Sending conversation to LLM ({self.model_name}):")
            # for msg in processed_messages:
            #     print(f"- {msg['role']}: {msg['content']}") # Debugging message content

            chat_completion = self.openai_client.chat.completions.create(
                model=self.model_name,
                messages=processed_messages,
                tools=self.available_tools_schema,
                tool_choice="auto", # Let the model decide if a tool call is needed
            )

            response_message = chat_completion.choices[0].message

            # Check if the LLM decided to call a tool
            if response_message.tool_calls:
                print("LLM requested tool call:")
                for tool_call in response_message.tool_calls:
                    function_name = tool_call.function.name
                    function_args = json.loads(tool_call.function.arguments)

                    # Ensure owner and repo are set, potentially overriding LLM's choice if needed
                    # Or add them if missing, based on the system prompt guidance
                    if 'owner' not in function_args:
                         function_args['owner'] = 'jimmyhealer' # Default owner
                         print(f"Injecting default owner: 'jimmyhealer'")
                    if 'repo' not in function_args:
                         function_args['repo'] = 'vocora' # Default repo
                         print(f"Injecting default repo: 'vocora'")


                    print(f"- Tool: {function_name}")
                    print(f"- Arguments: {function_args}")

                    # --- Execute the tool call via MCP ---
                    try:
                        print(f"Executing tool '{function_name}' via MCP server...")
                        result = await self.session.call_tool(function_name, function_args)
                        print(f"Tool '{function_name}' executed successfully.")
                        # Assuming the result.content contains the issue URL or relevant info
                        # The official github-mcp-server likely returns structured data.
                        # We might need to parse result.content based on its actual structure.
                        print(f"Tool Result Content: {result.content}")
                        return {
                            "tool_name": function_name,
                            "arguments": function_args,
                            "result": result.content # Pass the raw result back
                        }
                    except Exception as e:
                        print(f"Error calling tool '{function_name}' via MCP: {e}")
                        return { # Return error information
                             "tool_name": function_name,
                             "arguments": function_args,
                             "error": str(e)
                         }
            else:
                print("LLM decided no tool call is needed.")
                # print(f"LLM Response Text: {response_message.content}") # Log LLM's reasoning if needed
                return None

        except Exception as e:
            print(f"Error during LLM interaction or tool processing: {e}")
            return None # Indicate an error occurred

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

        result = await client.process_conversation(test_messages)

        if result and 'error' not in result:
            print(f"Test successful: Tool '{result['tool_name']}' called.")
            print(f"Result Content: {result['result']}")
        elif result and 'error' in result:
             print(f"Test Info: Tool '{result['tool_name']}' call failed with error: {result['error']}")
        else:
            print("Test Info: No tool call was made by the LLM.")

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