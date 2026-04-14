from pytubefix import YouTube
from pytubefix.cli import on_progress
from pydub import AudioSegment

url = "https://www.youtube.com/watch?v=nb8CnIo_-_A"

def main(video_url=url):
    print("running ytdownload")
    yt = YouTube(video_url, on_progress_callback=on_progress)
    print(yt.title)

    stream = yt.streams.get_audio_only()
    m4a_file = stream.download("./content", "output.m4a")
    wav_filename = './content/output.wav'
    sound = AudioSegment.from_file(m4a_file)
    sound.export(wav_filename, format="wav")
    return yt.title

if __name__ == "__main__":
    main()