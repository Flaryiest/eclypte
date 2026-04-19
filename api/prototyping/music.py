import librosa

def main():
    print("running music.py")
    filename = "./content/output.wav"
    y, sr = librosa.load(filename)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, hop_length=128)
    print('Estimated tempo: {:.2f} BPM'.format(round(tempo[0])))
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    return tempo[0], beat_times

if __name__ == "__main__":
    main()