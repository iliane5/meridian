#!/usr/bin/env python3

import requests
import json
import webbrowser
from typing import Optional, Dict, Any
import argparse
from rich.console import Console
from rich.panel import Panel
from rich import print as rprint

console = Console()

def test_tts(
    text: str,
    base_url: str = "http://localhost:5000",
    voice_id: Optional[str] = None,
    filename: Optional[str] = None,
    open_browser: bool = False
) -> Dict[str, Any]:
    """
    Test the TTS endpoint with the given parameters.
    
    Args:
        text: The text to convert to speech
        base_url: The base URL of the API
        voice_id: Optional voice ID to use
        filename: Optional filename for the audio file
        open_browser: Whether to open the audio URL in browser
    
    Returns:
        Dict containing the response from the API
    """
    # Prepare the request payload
    payload = {"text": text}
    if voice_id:
        payload["voice_id"] = voice_id
    if filename:
        payload["filename"] = filename
    
    # Make the request
    try:
        response = requests.post(
            f"{base_url}/api/tts",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        
        result = response.json()
        
        # Print the result in a nice format
        console.print(Panel(
            f"[green]Success![/green]\n"
            f"Audio URL: [blue]{result['audio_url']}[/blue]\n"
            f"Filename: {result['filename']}",
            title="TTS Response"
        ))
        
        # Open the audio URL in browser if requested
        if open_browser and result.get('audio_url'):
            webbrowser.open(result['audio_url'])
        
        return result
        
    except requests.exceptions.RequestException as e:
        console.print(Panel(
            f"[red]Error:[/red] {str(e)}",
            title="Request Failed"
        ))
        if hasattr(e.response, 'text'):
            try:
                error_details = json.loads(e.response.text)
                console.print(Panel(
                    json.dumps(error_details, indent=2),
                    title="Error Details"
                ))
            except:
                console.print(e.response.text)
        return None

def main():
    parser = argparse.ArgumentParser(description="Test the TTS endpoint")
    parser.add_argument("--text", help="Text to convert to speech")
    parser.add_argument("--url", default="http://localhost:5000", help="Base URL of the API")
    parser.add_argument("--voice", help="Voice ID to use")
    parser.add_argument("--filename", help="Filename for the audio file")
    parser.add_argument("--open", action="store_true", help="Open the audio URL in browser")
    args = parser.parse_args()
    
    # If no text provided, use a default test text
    text = args.text or "This is a test of the text to speech conversion. Hello, world!"
    
    # Run the test
    test_tts(
        text=text,
        base_url=args.url,
        voice_id=args.voice,
        filename=args.filename,
        open_browser=args.open
    )

if __name__ == "__main__":
    main() 