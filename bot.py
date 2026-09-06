import discord
from discord.ext import commands # Import commands
from discord import app_commands # Import application commands
import os
import asyncio
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from mcp_client import MCPClient
import json # For potentially parsing the result content
from typing import Optional, Dict, Any, List, Union  # For type hints

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN")
if not DISCORD_TOKEN:
    raise ValueError("DISCORD_TOKEN environment variable not set.")

# --- Configuration ---
MESSAGE_HISTORY_DURATION = timedelta(minutes=10) # Collect messages from the last 10 minutes
TARGET_REPO_OWNER = os.getenv("TARGET_REPO_OWNER", "vocora") # Default to vocora if not set
TARGET_REPO_NAME = os.getenv("TARGET_REPO_NAME", "vocora") # Default to vocora if not set
AUTO_DETECTION_ENABLED = False # Whether automatic issue detection is enabled
DEFAULT_ISSUE_LABELS = ["from-discord"]  # Default labels for created issues
# --- End Configuration ---

intents = discord.Intents.default()
intents.messages = True
intents.message_content = True # Ensure message content intent is enabled

# Use commands.Bot with no prefix for slash commands
client = commands.Bot(command_prefix=None, intents=intents)
mcp_client_instance = MCPClient() # Instantiate our MCPClient

# --- UI Components for Issue Confirmation ---
class IssueConfirmationView(discord.ui.View):
    def __init__(self, interaction_or_ctx: Union[discord.Interaction, commands.Context], issue_data: Dict[str, Any], timeout: int = 180):
        super().__init__(timeout=timeout)  # 3 minute timeout
        self.interaction_or_ctx = interaction_or_ctx
        self.issue_data = issue_data
        self.confirmed = False
        
    async def on_timeout(self):
        """Called when the view times out."""
        if not self.confirmed:
            if isinstance(self.interaction_or_ctx, discord.Interaction):
                try:
                    await self.interaction_or_ctx.edit_original_response(content="⏱️ Issue creation timed out. You can try again with `/issue`.", embed=None, view=None)
                except:
                    # If edit fails, the original message might have been deleted or interaction expired
                    pass
            else:
                await self.interaction_or_ctx.send("⏱️ Issue creation timed out. You can try again with `/issue`.")
            self.stop()
    
    # Confirm button
    @discord.ui.button(label="Confirm & Create", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        # Disable all buttons after confirmation
        for item in self.children:
            item.disabled = True
        
        # Edit the message to show disabled buttons, don't send a followup
        await interaction.response.edit_message(content="🔄 Creating issue...", view=self)
        
        self.stop()
    
    # Cancel button
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Issue creation cancelled.", view=None)
        self.stop()

# --- UI Components for Tool Call Confirmation ---
class ToolCallConfirmationView(discord.ui.View):
    def __init__(self, interaction_or_ctx: Union[discord.Interaction, commands.Context], tool_data: Dict[str, Any], timeout: int = 180):
        super().__init__(timeout=timeout)  # 3 minute timeout
        self.interaction_or_ctx = interaction_or_ctx
        self.tool_data = tool_data
        self.confirmed = False
        
    async def on_timeout(self):
        """Called when the view times out."""
        if not self.confirmed:
            if isinstance(self.interaction_or_ctx, discord.Interaction):
                try:
                    await self.interaction_or_ctx.edit_original_response(content="⏱️ Tool call confirmation timed out.", embed=None, view=None)
                except:
                    # If edit fails, the original message might have been deleted or interaction expired
                    pass
            else:
                await self.interaction_or_ctx.send("⏱️ Tool call confirmation timed out.")
            self.stop()
    
    # Confirm button
    @discord.ui.button(label="Confirm & Execute", style=discord.ButtonStyle.green, emoji="✅")
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        # Disable all buttons after confirmation
        for item in self.children:
            item.disabled = True
        
        # Edit the message to show disabled buttons, don't send a followup
        await interaction.response.edit_message(content="🔄 Executing tool call...", view=self)
        
        self.stop()
    
    # Cancel button
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="❌")
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="❌ Tool call cancelled.", view=None)
        self.stop()

# --- Helper Functions ---
def create_issue_confirmation_embed(issue_data: Dict[str, Any]) -> discord.Embed:
    """Creates an embed for issue confirmation."""
    embed = discord.Embed(
        title="Confirm GitHub Issue Creation",
        description="Please review the issue details and confirm or cancel.",
        color=discord.Color.blue(),
        timestamp=datetime.now()
    )
    
    # Add issue details
    embed.add_field(name="Title", value=issue_data.get("title", "[No Title]"), inline=False)
    
    # Add preview of the body (truncated if too long)
    body = issue_data.get("body", "[No Content]")
    if len(body) > 500:
        preview = body[:500] + "...\n[Content truncated, full conversation will be included]"
    else:
        preview = body
        
    embed.add_field(name="Body Preview", value=preview, inline=False)
    
    # Add labels
    labels = issue_data.get("labels", [])
    if labels:
        embed.add_field(name="Labels", value=", ".join(labels), inline=False)
    else:
        embed.add_field(name="Labels", value="[No Labels]", inline=False)
    
    # Add repository info
    repo_info = f"{issue_data.get('owner', TARGET_REPO_OWNER)}/{issue_data.get('repo', TARGET_REPO_NAME)}"
    embed.add_field(name="Repository", value=repo_info, inline=False)
    
    # Footer with instructions
    embed.set_footer(text="Use the buttons below to confirm or cancel.")
    
    return embed

def create_tool_call_confirmation_embed(tool_data: Dict[str, Any]) -> discord.Embed:
    """Creates an embed for tool call confirmation."""
    embed = discord.Embed(
        title="Confirm Tool Execution",
        description=f"The AI suggests executing the `{tool_data['tool_name']}` tool.",
        color=discord.Color.gold(),
        timestamp=datetime.now()
    )
    
    # Add tool details
    embed.add_field(name="Tool", value=tool_data['tool_name'], inline=False)
    
    # Add argument preview
    args_str = json.dumps(tool_data['arguments'], indent=2)
    if len(args_str) > 500:
        args_preview = args_str[:500] + "...\n[Arguments truncated]"
    else:
        args_preview = args_str
        
    embed.add_field(name="Arguments", value=f"```json\n{args_preview}\n```", inline=False)
    
    # Footer with instructions
    embed.set_footer(text="Use the buttons below to confirm or cancel this action.")
    
    return embed

async def collect_recent_messages(channel: discord.TextChannel, duration: timedelta) -> tuple:
    """Collects recent messages from a channel, formatted for processing."""
    print(f"Collecting messages from the last {duration} in #{channel.name}...")
    history_limit_time = datetime.now(timezone.utc) - duration
    recent_messages_formatted = []
    raw_messages_content = [] # Store raw content for issue body

    try:
        async for msg in channel.history(limit=100, after=history_limit_time, oldest_first=True):
            # Format messages for the LLM (OpenAI format)
            if msg.author == client.user:
                # TODO: Add support for bot messages, but not including info messages
                continue
            role = "user"
            user_name = str(msg.author.display_name or msg.author.name)
            formatted_content = f"{user_name}: {msg.content}"
            recent_messages_formatted.append({
                "role": role,
                "content": formatted_content
            })
            raw_messages_content.append(formatted_content) # Add raw formatted line to list
        print(f"Collected {len(recent_messages_formatted)} messages.")
        return recent_messages_formatted, "\n".join(raw_messages_content) # Return both formats
    except discord.Forbidden:
        print(f"Error: Missing permissions to read history in channel {channel.name}")
        return [], "" # Return empty lists on permission error
    except Exception as e:
        print(f"Error collecting message history in #{channel.name}: {e}")
        return [], "" # Return empty lists on other errors

async def handle_tool_execution(interaction_or_ctx: Union[discord.Interaction, commands.Context], 
                                tool_data: Dict[str, Any], 
                                is_original_message: bool = False):
    """
    Handle tool execution after confirmation.
    
    Args:
        interaction_or_ctx: The interaction or context object from Discord
        tool_data: The tool data to execute
        is_original_message: Whether this is handling the original message or a reply
    """
    tool_name = tool_data["tool_name"]
    
    # Special handling for issue creation
    if tool_name == "create_issue":        
        # Add default labels if none are specified
        if "labels" not in tool_data["arguments"]:
            tool_data["arguments"]["labels"] = DEFAULT_ISSUE_LABELS
        else:
            tool_data["arguments"]["labels"].append("from-discord")
    
    # Execute the tool call
    result = await mcp_client_instance.execute_tool_call(tool_data["tool_name"], tool_data["arguments"])
    
    # Handle the result
    if "error" in result:
        error_message = f"🚨 Failed to execute {tool_name}. Error: {result['error']}"
        if isinstance(interaction_or_ctx, discord.Interaction):
            if is_original_message:
                await interaction_or_ctx.edit_original_response(content=error_message)
            else:
                await interaction_or_ctx.followup.send(error_message)
        else:
            await interaction_or_ctx.send(error_message)
        return False, None
    
    # Success! Parse result for specific tools
    if tool_name == "create_issue":
        issue_url = "Unknown (Check MCP Server logs)"
        # Try to parse the URL from result
        try:
            result_content = result["result"]
            
            # Handle TextContent object if that's what we received
            if hasattr(result_content, 'text'):
                result_content = result_content.text
            
            # Handle list of TextContent objects
            if isinstance(result_content, list) and len(result_content) > 0 and hasattr(result_content[0], 'text'):
                result_content = result_content[0].text
            
            # Now process the content which should be a string or dict
            if isinstance(result_content, str):
                try:
                    result_data = json.loads(result_content)
                    if isinstance(result_data, dict):
                        issue_url = result_data.get("html_url", issue_url)
                        print(f"Successfully parsed issue URL: {issue_url}")
                except json.JSONDecodeError:
                    print(f"Could not parse result as JSON: {result_content[:100]}...")
                    if result_content.startswith('http'):
                        issue_url = result_content
            elif isinstance(result_content, dict):
                issue_url = result_content.get("html_url", issue_url)
        except Exception as parse_err:
            print(f"Could not parse issue URL from result content: {parse_err}")
            print(f"Raw result content type: {type(result['result'])}")
            
        success_message = (
            f"✅ Successfully created GitHub Issue: **{tool_data['arguments'].get('title', 'New Issue')}**\n"
            f"🔗 Link: <{issue_url}>"
        )
        
        if isinstance(interaction_or_ctx, discord.Interaction):
            if is_original_message:
                await interaction_or_ctx.edit_original_response(content=success_message)
            else:
                await interaction_or_ctx.followup.send(success_message)
        else:
            await interaction_or_ctx.send(success_message)
        return True, issue_url
    
    # Generic success handling for other tools
    success_message = f"✅ Successfully executed {tool_name}."
    if isinstance(interaction_or_ctx, discord.Interaction):
        if is_original_message:
            await interaction_or_ctx.edit_original_response(content=success_message)
        else:
            await interaction_or_ctx.followup.send(success_message)
    else:
        await interaction_or_ctx.send(success_message)
    return True, result["result"]

async def process_conversation_with_confirmation(interaction_or_ctx: Union[discord.Interaction, commands.Context], 
                                                messages_llm: List[Dict[str, Any]], 
                                                raw_conversation: str,
                                                custom_title: Optional[str] = None):
    """
    Process a conversation with LLM, get confirmation for any tool calls, and execute if confirmed.
    This is the unified logic used by both auto-detection and manual issue creation.
    
    Args:
        interaction_or_ctx: The interaction or context object
        messages_llm: Formatted messages for LLM
        raw_conversation: Raw conversation text
        custom_title: Optional custom title for issue creation
    """
    # LLM analyze step
    suggested, tool_data = await mcp_client_instance.analyze_conversation(messages_llm)
    
    if not suggested or not tool_data:
        # No tool call suggested
        if isinstance(interaction_or_ctx, discord.Interaction):
            await interaction_or_ctx.edit_original_response(
                content="🤔 I don't see a clear need to create an issue based on this conversation. "
                        "You can try again or use `/issue` with a custom title."
            )
        else:
            # This is from auto-detection, don't respond if nothing detected
            pass
        return False, None
    
    # A tool call was suggested
    tool_name = tool_data["tool_name"]
    
    # For create_issue tool, handle potential custom title
    if tool_name == "create_issue" and custom_title:
        tool_data["arguments"]["title"] = custom_title
    
    # Store raw conversation for issue body if needed
    if tool_name == "create_issue":
        tool_data["raw_conversation"] = raw_conversation
    
    # Create confirmation UI
    embed = create_tool_call_confirmation_embed(tool_data)
    view = ToolCallConfirmationView(interaction_or_ctx, tool_data)
    
    # Send/edit message for confirmation
    if isinstance(interaction_or_ctx, discord.Interaction):
        await interaction_or_ctx.edit_original_response(content=None, embed=embed, view=view)
    else:
        confirmation_msg = await interaction_or_ctx.reply(embed=embed, view=view)
        # For regular context, update the interaction_or_ctx to be the new message
        # This will allow us to edit this message later
        view.interaction_or_ctx = confirmation_msg
    
    # Wait for user interaction
    await view.wait()
    
    # Process result of confirmation
    if view.confirmed:
        return await handle_tool_execution(view.interaction_or_ctx, view.tool_data, True)
    
    return False, None

# --- Bot Events ---
@client.event
async def on_ready():
    print(f'Logged in as {client.user}')
    print('Connecting to MCP server...')
    try:
        await mcp_client_instance.connect_to_server()
        print('MCP Client connected successfully.')
        
        # Sync the commands with Discord
        try:
            synced = await client.tree.sync()
            print(f"Synced {len(synced)} command(s)")
        except Exception as e:
            print(f"Failed to sync commands: {e}")
            
    except Exception as e:
        print(f'Failed to connect MCP client: {e}')
        # Optionally, you might want to shut down the bot if MCP connection fails
        # await client.close()

@client.event
async def on_message(message):
    # Ignore messages from the bot itself
    if message.author == client.user:
        return

    # Only process messages in guilds (servers), not DMs
    if not message.guild:
        return

    print(f"\n[{datetime.now()}] Received message from {message.author} in #{message.channel}: {message.content}")

    # Skip automatic processing if disabled
    if not AUTO_DETECTION_ENABLED:
        print("Automatic issue detection is disabled. Skipping LLM processing.")
        return

    # Use the helper function to collect messages
    recent_messages_llm, raw_conversation = await collect_recent_messages(message.channel, MESSAGE_HISTORY_DURATION)

    if not recent_messages_llm:
        print("No recent messages found to process for LLM.")
        return

    # Append the current message to ensure it's included in LLM context
    current_user_name = str(message.author.display_name or message.author.name)
    recent_messages_llm.append({
        "role": "user",
        "content": f"{current_user_name}: {message.content}"
    })
    
    # Add current message to raw conversation too
    raw_conversation += f"\n{current_user_name}: {message.content}"

    # Process with unified logic (no need for defer/thinking state in auto-detection)
    await process_conversation_with_confirmation(message, recent_messages_llm, raw_conversation)

# --- Slash Commands ---
@client.tree.command(name="issue", description="Create a GitHub issue from recent chat history")
@app_commands.describe(title="Custom title for the GitHub issue (optional)")
async def slash_issue(interaction: discord.Interaction, title: Optional[str] = None):
    """Create a GitHub issue from recent chat history"""
    print(f"\n[{datetime.now()}] Slash command /issue triggered by {interaction.user} in #{interaction.channel}")
    
    # Need to defer the response as we'll be doing async operations that might take time
    await interaction.response.defer(thinking=True)
    
    if not mcp_client_instance.session:
        await interaction.edit_original_response(content="🚨 Error: The connection to the GitHub MCP Server is not active. Cannot create issue.")
        return

    # Use helper to get messages (both formats)
    recent_messages_llm, raw_conversation = await collect_recent_messages(interaction.channel, MESSAGE_HISTORY_DURATION)

    if not recent_messages_llm:
        await interaction.edit_original_response(content="❌ Could not find any recent messages to include in the issue body.")
        return
    
    # Process with unified logic
    await process_conversation_with_confirmation(interaction, recent_messages_llm, raw_conversation, title)

@client.tree.command(name="autodetect", description="Toggle or check automatic issue detection status")
@app_commands.describe(setting="Turn automatic detection on or off (leave empty to check current status)")
@app_commands.choices(setting=[
    app_commands.Choice(name="On", value="on"),
    app_commands.Choice(name="Off", value="off")
])
async def slash_autodetect(interaction: discord.Interaction, setting: Optional[app_commands.Choice[str]] = None):
    """Toggle or check automatic issue detection status"""
    global AUTO_DETECTION_ENABLED
    await interaction.response.defer(ephemeral=True)  # Make the response only visible to the command user
    
    if setting is None:
        # Report current status
        status = "enabled" if AUTO_DETECTION_ENABLED else "disabled"
        await interaction.edit_original_response(content=f"🔍 Automatic issue detection is currently **{status}**.\nUse `/autodetect` command with On/Off option to change.")
        return
    
    if setting.value == "on":
        AUTO_DETECTION_ENABLED = True
        await interaction.edit_original_response(content="✅ Automatic issue detection has been **enabled**. The bot will now monitor conversations for potential issues.")
    elif setting.value == "off":
        AUTO_DETECTION_ENABLED = False
        await interaction.edit_original_response(content="🛑 Automatic issue detection has been **disabled**. You can still create issues manually with `/issue`.")
    
    print(f"[{datetime.now()}] Automatic issue detection set to: {AUTO_DETECTION_ENABLED} by {interaction.user}")

# --- Main Execution ---
async def main():
    async with client:
        try:
            print("Starting Discord bot...")
            await client.start(DISCORD_TOKEN)
        except discord.LoginFailure:
            print("Error: Invalid Discord Token. Please check your .env file.")
        except Exception as e:
            print(f"Error starting Discord bot: {e}")
        finally:
            print("Cleaning up MCP client...")
            await mcp_client_instance.cleanup()
            print("Bot shutdown complete.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot stopped manually.")
 