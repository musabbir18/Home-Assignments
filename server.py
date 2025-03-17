from flask import Flask, request, jsonify
from flask_cors import CORS
 
app = Flask(__name__)
CORS(app)
 
def estimate_audio_length(text, words_per_second=2):
    words = text.split()
    return len(words) / words_per_second
 
def trim_text(text, max_duration=60, words_per_second=2):
    words = text.split()
    max_words = max_duration * words_per_second
    if len(words) <= max_words:
        return text
    start = (len(words) - max_words) // 2
    end = start + max_words
    return ' '.join(words[start:end])
 
@app.route('/validate_audio_length', methods=['POST'])
def validate_audio():
    data = request.json
    text = data['text']
    audio_length = data.get('audio_length', estimate_audio_length(text))
 
    if audio_length > 60:
        # Trim the text to ensure audio length does not exceed 60 seconds
        text = trim_text(text)
    return jsonify({'validated_text': text, 'audio_length': audio_length})
 
if __name__ == '__main__':
    app.run(debug=True)