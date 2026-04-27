import pyttsx3


def initialize_engine():
    """
    Initializes the text-to-speech engine and sets the speed and voice.
    Returns:
        pyttsx3.Engine: The initialized engine.
    """
    engine = pyttsx3.init()
    
    engine.setProperty('rate', 175) 
    
    voices = engine.getProperty('voices')
    engine.setProperty('voice', voices[0].id) 
    
    return engine


def speak(text: str) -> None:
    """
    Speaks the given text using the text-to-speech engine.
    Args:
        text (str): The text to speak.
    """
    engine = initialize_engine()
    
    print(f"\n[APEX]: {text}")
    
    engine.say(text)
    engine.runAndWait()

if __name__ == "__main__":
    speak("Good morning Chief. All systems are operational. I am ready to begin your briefing.")