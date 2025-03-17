import asyncio
import logging
import requests
from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
    metrics,
)
from livekit.agents.pipeline import VoicePipelineAgent
from livekit.plugins import deepgram, openai, silero
 
load_dotenv()
logger = logging.getLogger("voice-assistant")
 
 
def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()
 
 
async def entrypoint(ctx: JobContext):
    initial_ctx = llm.ChatContext().append(
        role="system",
        text=(
            "You are a voice assistant created by LiveKit. Your interface with users will be voice. "
            "You should use short and concise responses, and avoiding usage of unpronouncable punctuation."
        ),
    )
   
    # Modified: Properly implement the before_tts_cb function
    def before_tts_callback(assistant, text: str) -> str:
        try:
            logger.info(f"Original text sent for validation: {text[:50]}...")
            response = requests.post(
                ' https://1813-183-82-34-206.ngrok-free.app/validate_audio_length',
                json={'text': text},
                timeout=5  # Add timeout for reliability
            )
           
            if response.status_code == 200:
                data = response.json()
                validated_text = data.get('validated_text', text)
                logger.info(f"Original length: {len(text)}, Validated length: {len(validated_text)}")
               
                # If texts are different, log that trimming occurred
                if text != validated_text:
                    logger.info("Text was trimmed by validation server")
               
                return validated_text
            else:
                logger.error(f"Validation server error: {response.status_code}, {response.text}")
                return text
        except Exception as e:
            logger.error(f"Error in before_tts_callback: {str(e)}")
            return text
   
    logger.info(f"connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
 
    # wait for the first participant to connect
    participant = await ctx.wait_for_participant()
    logger.info(f"starting voice assistant for participant {participant.identity}")
 
    dg_model = "nova-3-general"
    if participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP:
        # use a model optimized for telephony
        dg_model = "nova-2-phonecall"
 
    agent = VoicePipelineAgent(
        vad=ctx.proc.userdata["vad"],
        stt=deepgram.STT(model=dg_model),
        llm=openai.LLM(),
        tts=openai.TTS(),
        chat_ctx=initial_ctx,
        before_tts_cb=before_tts_callback,
    )
 
    agent.start(ctx.room, participant)
 
    usage_collector = metrics.UsageCollector()
 
    @agent.on("metrics_collected")
    def _on_metrics_collected(mtrcs: metrics.AgentMetrics):
        metrics.log_metrics(mtrcs)
        usage_collector.collect(mtrcs)
 
    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Usage: ${summary}")
 
    ctx.add_shutdown_callback(log_usage)
 
    # listen to incoming chat messages
    chat = rtc.ChatManager(ctx.room)
 
    async def answer_from_text(txt: str):
        chat_ctx = agent.chat_ctx.copy()
        chat_ctx.append(role="user", text=txt)
 
        response_text = ""
        async for chunk in agent.llm.chat(chat_ctx=chat_ctx):
            if chunk.choices and chunk.choices[0].delta.content:
                response_text += chunk.choices[0].delta.content
       
        logger.info(f"LLM generated response: {response_text[:50]}...")
        await agent.say(response_text, allow_interruptions=True)
 
    @chat.on("message_received")
    def on_chat_received(msg: rtc.ChatMessage):
        if msg.message:
            asyncio.create_task(answer_from_text(msg.message))
 
    await agent.say("Hey, how can I help you today?", allow_interruptions=True)
 
 
if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        ),
    )