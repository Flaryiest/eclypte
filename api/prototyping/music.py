import librosa
import syncedlyrics
def main():
    print("running music.py")
    filename = "./content/output.wav"
    y, sr = librosa.load(filename)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=128)
    print('Estimated tempo: {:.2f} BPM'.format(round(tempo[0])))
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)

    lrc = syncedlyrics.search("Dominic Fike Babydoll Official Audio")
    with open("./content/lyrics.txt", "w", encoding="utf-8") as f:
        f.write(lrc or "")
    print(lrc)

main()