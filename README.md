# LocalTranslator

A desktop application for translating text and subtitle files using local large language models through KoboldCPP.

![TranslatorAplication](https://github.com/user-attachments/assets/16dd9324-fda9-4fa2-ac05-ac969c498092)

## Features

- **Text and subtitle translation**: Translate both free-form text and SRT subtitle files
- **Local LLM support**: Uses KoboldCPP as a backend to run translations locally on your hardware
- **Batch processing**: Translates subtitles in configurable batches to optimize performance and accuracy
- **Import/Export**: Easily import SRT files and export translations
- **Cross-platform**: Built with PyQt5 to run on Windows, macOS, and Linux

## Installation

### Prerequisites

- Python 3.6+
- KoboldCPP server running locally
- Recommended LLM: Gemma 3 27B abliterated (provides excellent translation quality). Depending on the language and hardware, Gemma 3 12B abliterated might also be a good choice. Abliterated models are recommended over the original Gemma 3 models because the original models are too censored and often refuse to translate any controversial texts.

### Setup

1. Clone this repository:
```bash
git clone https://github.com/PasiKoodaa/LocalTranslator
cd LocalTranslator
```
2. Create a new conda environment and activate it:
```bash
conda create -n LocalTranslator python==3.9
conda activate LocalTranslator
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Run the application:
```bash
python app.py
```

## Using LocalTranslator

### Setting Up the Server Connection

1. Start your KoboldCPP instance with your preferred LLM (Gemma 3 27B abliterated recommended)
2. Click "Connect" on LocalTranslator GUI and verify the connection status changes to "Connected"

### Free Text Translation

1. Enter the text you want to translate in the source text area
2. Select source and target languages
3. Click "Translate"
4. Use "Copy to Clipboard" to easily use the translated text elsewhere

### Subtitle Translation

1. Import an SRT file or paste its content directly
2. Select source and target languages
3. Configure batch size and delay between batches
4. Click "Translate SRT"
5. Export the translated subtitles when complete


## Troubleshooting

- **Connection issues**: Verify KoboldCPP is running and accessible at the specified URL
- **Incomplete translations**: Try reducing batch size
- **Slow performance**: Try Gemma 3 12B abliterated or run on a machine with a better GPU/CPU.
- **My language is not in the app**: Edit the main.py code; the LLM (Gemma 3 abliterated) probably can understand and write in your language.


