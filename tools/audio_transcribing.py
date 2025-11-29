from langchain.tools import tool
import speech_recognition as sr
from pydub import AudioSegment
import os

@tool
def transcribe_audio(file_path: str) -> str:
    """
    Transcribe an MP3 or WAV audio file into text using Google's Web Speech API.

    Args:
        file_path (str): Path to the input audio file (.mp3 or .wav).

    Returns:
        str: The transcribed text from the audio.

    Notes:
        - MP3 files are automatically converted to WAV.
        - Requires `pydub` and `speech_recognition` packages.
        - Uses Google's free recognize_google() API (requires internet).
    """
    try:
        # Build full path
        file_path = os.path.join("LLMFiles", file_path)
        print(f"Processing audio file: {file_path}")

        if not os.path.exists(file_path):
            return f"Error: File not found at {file_path}"

        final_path = file_path

        # Convert MP3 → WAV if needed with proper audio settings
        if file_path.lower().endswith(".mp3"):
            print("Converting MP3 to WAV...")
            sound = AudioSegment.from_mp3(file_path)

            # Convert to mono and set proper sample rate for speech recognition
            sound = sound.set_channels(1).set_frame_rate(16000)

            final_path = file_path.replace(".mp3", ".wav")
            sound.export(final_path, format="wav")
            print(f"Converted to: {final_path}")

        # Speech recognition with improved settings
        recognizer = sr.Recognizer()

        # Adjust recognizer settings for better accuracy
        recognizer.energy_threshold = 300
        recognizer.dynamic_energy_threshold = True
        recognizer.pause_threshold = 0.8

        print("Starting transcription...")
        with sr.AudioFile(final_path) as source:
            # Record the audio with adjustment for ambient noise
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
            audio_data = recognizer.record(source)

            # Try transcription with show_all to get alternatives if needed
            try:
                text = recognizer.recognize_google(audio_data, show_all=False)
                print(f"Transcription successful: {text}")
            except sr.UnknownValueError:
                return "Error: Could not understand audio - speech may be unclear or too noisy"
            except sr.RequestError as e:
                return f"Error: Could not request results from Google Speech Recognition service: {e}"

        # Clean up temporary WAV file if we converted
        if final_path != file_path and os.path.exists(final_path):
            os.remove(final_path)
            print("Cleaned up temporary WAV file")

        return text

    except FileNotFoundError as e:
        return f"Error: Audio file not found - {e}"
    except Exception as e:
        return f"Error during transcription: {type(e).__name__} - {str(e)}"
