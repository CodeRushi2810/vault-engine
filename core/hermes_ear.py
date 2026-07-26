import time
import speech_recognition as sr
import threading
import sys
import requests
import win32com.client
import pythoncom
import random
import os
import json

from core.system_logger import setup_logger

def is_hermes_enabled():
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "system_config.json")
    try:
        with open(config_path, "r") as f:
            cfg = json.load(f)
            return cfg.get("engine", {}).get("features", {}).get("voice_orb", True)
    except Exception:
        return True
logger = setup_logger("hermes_ear")

API_BRIDGE_URL = "http://127.0.0.1:8000/api/hermes/bridge"

def speak(text):
    try:
        # 1. Send Speaking Event to Dashboard
        send_event("HERMES_SPEAKING", text)
        
        # 2. Speak synchronously using Windows SAPI (Zero Delay!)
        pythoncom.CoInitialize()
        speaker = win32com.client.Dispatch("SAPI.SpVoice")
        
        # Select David (index 0 / Microsoft David)
        voices = speaker.GetVoices()
        for i in range(voices.Count):
            if "David" in voices.Item(i).GetDescription():
                speaker.Voice = voices.Item(i)
                break
        
        # Wrap the text in the XML pitch modifier you loved!
        xml_text = f"<pitch absmiddle='-10'>{text}</pitch>"
        
        # Increase the pace as requested
        speaker.Rate = 2
        
        # 8 = SVSFIsXML flag
        speaker.Speak(xml_text, 8)
        
    except Exception as e:
        logger.error(f"TTS Error: {e}")
    finally:
        pythoncom.CoUninitialize()
        send_event("HERMES_SLEEP")

def send_event(event_type, transcript=None):
    try:
        payload = {"type": event_type}
        if transcript:
            payload["transcript"] = transcript
        requests.post(API_BRIDGE_URL, json=payload, timeout=1)
    except Exception as e:
        logger.error(f"Failed to send event: {e}")

def listen_for_wake_word():
    recognizer = sr.Recognizer()
    recognizer.energy_threshold = 300
    recognizer.dynamic_energy_threshold = False  # Fixed: Stops it from aggressively cutting off quiet words
    recognizer.pause_threshold = 2.0  # Fixed: Gives you more time to speak before cutting off
    
    with sr.Microphone() as source:
        logger.info("\033[93mCalibrating microphone for ambient noise...\033[0m")
        recognizer.adjust_for_ambient_noise(source, duration=2)
        logger.info("\033[92mSystem Online. Listening for 'Hey Hermes'...\033[0m")
        
        while True:
            if not is_hermes_enabled():
                time.sleep(2)
                continue
                
            try:
                audio = recognizer.listen(source, timeout=2, phrase_time_limit=10)
                try:
                    transcript = recognizer.recognize_google(audio).lower()
                    if transcript:
                        logger.info(f"Heard: {transcript}")
                        
                        # 1. Send what we heard to the dashboard
                        send_event("HERMES_TRANSCRIPT", transcript)
                        
                        # 2. Process command via API
                        try:
                            resp = requests.post("http://127.0.0.1:8000/api/hermes/command", json={"command": transcript}, timeout=3)
                            if resp.status_code == 200:
                                data = resp.json()
                                reply_text = data.get("response", "")
                                if reply_text:
                                    logger.info(f"Agent Response: {reply_text}")
                                    speak(reply_text)
                                else:
                                    send_event("HERMES_SLEEP")
                            else:
                                send_event("HERMES_SLEEP")
                        except Exception as e:
                            logger.error(f"Failed to process command: {e}")
                            send_event("HERMES_SLEEP")
                            
                except sr.UnknownValueError:
                    pass
                except sr.RequestError as e:
                    logger.error(f"Could not request results; {e}")
            except sr.WaitTimeoutError:
                continue
            except Exception as e:
                logger.error(f"Error in ear loop: {e}")
                time.sleep(1)

if __name__ == "__main__":
    logger.info("Starting Hermes Ear (Wake Word Engine)...")
    t = threading.Thread(target=listen_for_wake_word, daemon=True)
    t.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down Hermes Ear.")
        sys.exit(0)
