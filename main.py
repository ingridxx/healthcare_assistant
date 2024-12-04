import asyncio
import base64
import json
import os
from dotenv import load_dotenv
from typing import Union
import httpx
import singlestoredb as s2
from hume.client import AsyncHumeClient
from hume.empathic_voice.chat.socket_client import ChatConnectOptions, ChatWebsocketConnection
from hume.empathic_voice.chat.types import SubscribeEvent
from hume.empathic_voice import UserInput, ToolCallMessage, ToolErrorMessage, ToolResponseMessage
from hume.core.api_error import ApiError
from hume import MicrophoneInterface, Stream
from utils import print_prompt, extract_top_n_emotions, print_emotion_scores

load_dotenv()

# Create a dictionary with the required parameters
connection_params = {
    "host": os.getenv("SINGLESTORE_HOST"),
    "port": 3306,
    "user": os.getenv("SINGLESTORE_USER"),
    "password": os.getenv("SINGLESTORE_PASSWORD"),
    "database": os.getenv("SINGLESTORE_DB"),
}

# Retrieve the API key, Secret key, and EVI config id from the environment variables
HUME_API_KEY = os.getenv("HUME_API_KEY")
HUME_SECRET_KEY = os.getenv("HUME_SECRET_KEY")
HUME_CONFIG_ID = os.getenv("HUME_CONFIG_ID")


class WebSocketHandler:
    def __init__(self):
        """Construct the WebSocketHandler, initially assigning the socket to None and the byte stream to a new Stream object."""
        self.socket = None
        self.byte_strs = Stream.new()

    def set_socket(self, socket: ChatWebsocketConnection):
        """Set the socket.
        
        This method assigns the provided asynchronous WebSocket connection
        to the instance variable `self.socket`. It is invoked after successfully
        establishing a connection using the client's connect method.

        Args:
            socket (ChatWebsocketConnection): EVI asynchronous WebSocket returned by the client's connect method.
        """
        self.socket = socket

    async def handle_tool_call(self, message: ToolCallMessage) -> Union[ToolCallMessage, ToolErrorMessage]:
        """Functionality which executes when a tool call is invoked.
        
        Args:
            message (ToolCallMessage): The message sent when a tool call is invoked. See it in the API Reference [here](https://dev.hume.ai/reference/empathic-voice-interface-evi/chat/chat#receive.Tool%20Call%20Message.name).
        
        Returns:
            Union[ToolResponseMessage, ToolErrorMessage]: Returns a [ToolResponseMessage](https://dev.hume.ai/reference/empathic-voice-interface-evi/chat/chat#send.Tool%20Response%20Message.type) if the tool call is succesful or a [ToolErrorMessage](https://dev.hume.ai/reference/empathic-voice-interface-evi/chat/chat#send.Tool%20Error%20Message.type) if the tool call fails. 
        """

        # Obtain the name, ID, and parameters of the tool call
        tool_name = message.name
        tool_call_id = message.tool_call_id

        # Parse the stringified JSON parameters into a dictionary
        try:
            tool_parameters = json.loads(message.parameters)
        except json.JSONDecodeError:
            resp = ToolErrorMessage(
                tool_call_id=tool_call_id,
                content="Invalid parameters format.",
                error="JSONDecodeError"
            )
            await self.socket.send_tool_error(resp)
            print(f"(Sent ToolErrorMessage for tool_call_id {tool_call_id} due to JSON decode error.)\n")
            return

        if tool_name == "fetch_health_metrics":
            health_metrics = await fetch_health_metrics()
    
            return ToolResponseMessage(
                tool_call_id=tool_call_id,
                content=json.dumps({"data": health_metrics}),
            )
        else:
            print(f"Unknown tool: {tool_name}")
            return None

    async def insert_messages(messages):
        s2_conn = s2.connect()
        s2_cur = s2_conn.cursor()
        try:
            for message in messages:
                query = """
                INSERT INTO chat_messages (event_id, chat_id, timestamp, emotion_features, message_text)
                VALUES (%s, %s, FROM_UNIXTIME(%s), %s, %s)
                ON DUPLICATE KEY UPDATE message_text = VALUES(message_text);
                """
                s2_cur.execute(query,(
                    message["id"],
                    message["chat_id"],
                    message["timestamp"] / 1000,  # Convert milliseconds to seconds
                    message["emotion_features"],
                    message["message_text"]
                ))
                s2_conn.commit()
        finally:
            s2_conn.close() 
            
    
    async def on_open(self):
        """Logic invoked when the WebSocket connection is opened."""
        print("WebSocket connection opened.")

    async def on_message(self, message: SubscribeEvent):
        # Create an empty dictionary to store expression inference scores
        scores = {}

        if message.type == "chat_metadata":
            message_type = message.type.upper()
            chat_id = message.chat_id
            chat_group_id = message.chat_group_id
            text = f"<{message_type}> Chat ID: {chat_id}, Chat Group ID: {chat_group_id}"
        elif message.type == "user_message":
            # Extract relevant data from the user message
            event_id = message.id
            chat_id = message.chat_id
            timestamp = message.timestamp
            message_text = message.content
            emotion_features = message.models.prosody.scores 

            # Prepare the message dictionary
            user_message = {
                "id": event_id,
                "chat_id": chat_id,
                "timestamp": timestamp,
                "emotion_features": json.dumps(emotion_features),  # Store as JSON string
                "message_text": message_text
            }

            # Insert the message into the database
            await self.insert_messages([user_message])
            print(f"Inserted user message {event_id} into chat_messages table.")
            text = f"USER: {message_text}"
        elif message.type == "assistant_message":
            message_text = message.message.content
            text = f"ASSISTANT: {message_text}"
            if message.from_text is False:
                scores = dict(message.models.prosody.scores)
        elif message.type == "tool_call":
            if message.tool_type != "builtin":
                await self.handle_tool_call(message)
            text = f"<TOOL_CALL> Tool name: {message.name}"
        elif message.type == "audio_output":
            message_str: str = message.data
            message_bytes = base64.b64decode(message_str.encode("utf-8"))
            await self.byte_strs.put(message_bytes)
            return
        elif message.type == "error":
            error_message: str = message.message
            error_code: str = message.code
            raise ApiError(f"Error ({error_code}): {error_message}")
        else:
            message_type = message.type.upper()
            text = f"<{message_type}>"
        
        print_prompt(text)

        if len(scores) > 0:
            top_3_emotions = extract_top_n_emotions(scores, 3)
            print_emotion_scores(top_3_emotions)
            print("")
        else:
            print("")
        
    async def on_close(self):
        """Logic invoked when the WebSocket connection is closed."""
        print("WebSocket connection closed.")

    async def on_error(self, error):
        """Logic invoked when an error occurs in the WebSocket connection.
        
        See the full list of errors [here](https://dev.hume.ai/docs/resources/errors).

        Args:
            error (Exception): The error that occurred during the WebSocket communication.
        """
        print(f"Error: {error}")

async def fetch_health_metrics():
    """Fetch health metrics from SingleStore db"""
    s2_conn = s2.connect(**connection_params)
    try:
        s2_cur = s2_conn.cursor()
        s2_cur.execute("""
        SELECT heart_rate, blood_pressure, glucose_level, activity_level FROM vitals ORDER BY timestamp DESC LIMIT 1;
        """)
        results = s2_cur.fetchall()

        # Convert results to a list of dictionaries
        columns = [col[0] for col in s2_cur.description]
        metrics = [dict(zip(columns, row)) for row in results]

        return metrics

    finally:
        s2_conn.close()

async def sending_handler(socket: ChatWebsocketConnection):
    """Handle sending a message over the socket.

    This method waits 3 seconds and sends a UserInput message, which takes a `text` parameter as input.
    - https://dev.hume.ai/reference/empathic-voice-interface-evi/chat/chat#send.User%20Input.type
    
    See the full list of messages to send [here](https://dev.hume.ai/reference/empathic-voice-interface-evi/chat/chat#send).

    Args:
        socket (ChatWebsocketConnection): The WebSocket connection used to send messages.
    """
    # Wait 3 seconds before executing the rest of the method
    await asyncio.sleep(3)

    # Construct a user input message
    # user_input_message = UserInput(text="Hello there!")

    # Send the user input as text to the socket
    # await socket.send_user_input(user_input_message)

async def main() -> None:
    # Initialize the asynchronous client, authenticating with your API key
    client = AsyncHumeClient(api_key=HUME_API_KEY)

    # Define options for the WebSocket connection, such as an EVI config id and a secret key for token authentication
    # See the full list of query parameters here: https://dev.hume.ai/reference/empathic-voice-interface-evi/chat/chat#request.query
    options = ChatConnectOptions(config_id=HUME_CONFIG_ID, secret_key=HUME_SECRET_KEY)

    # Instantiate the WebSocketHandler
    websocket_handler = WebSocketHandler()

    # Open the WebSocket connection with the configuration options and the handler's functions
    async with client.empathic_voice.chat.connect_with_callbacks(
        options=options,
        on_open=websocket_handler.on_open,
        on_message=websocket_handler.on_message,
        on_close=websocket_handler.on_close,
        on_error=websocket_handler.on_error
    ) as socket:

        # Set the socket instance in the handler
        websocket_handler.set_socket(socket)

        # Create an asynchronous task to continuously detect and process input from the microphone, as well as play audio
        microphone_task = asyncio.create_task(
            MicrophoneInterface.start(
                socket,
                allow_user_interrupt=False,
                byte_stream=websocket_handler.byte_strs
            )
        )
        
        # Create an asynchronous task to send messages over the WebSocket connection
        message_sending_task = asyncio.create_task(sending_handler(socket))
        
        # Schedule the coroutines to occur simultaneously
        await asyncio.gather(microphone_task, message_sending_task)

if __name__ == "__main__":
    asyncio.run(main())