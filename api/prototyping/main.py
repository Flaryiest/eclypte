import ytdownload
import analysis
import lyrics

def main():
    title = ytdownload.main(ytdownload.url)
    analysis.analyze("./content/output.wav", "./content/output.json")
    lyrics.main(title)

if __name__ == "__main__":
    main()
