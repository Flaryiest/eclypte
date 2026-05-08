# Eclypte  
A multipurpose AI video editing pipeline. Hosted version can be found here: [https://eclypte.vercel.app/](https://eclypte.vercel.app/). Would recommend looking at the Shape of You - Super Mario Galaxy Movie example at /demo.

Initially created this project in order to create short-form content (particularly cool anime/movie edits) but the infrastructure works arguably better for normal editing activities, at least until I develop it more.

Eclypte lets a user upload a WAV song and an MP4 source audio, then runs both through an analysis pipeline. The song analysis extracts beats, downbeats, tempo, structure, and energy. The video analysis detects scenes, motion, visual energy, and impact momentum (largely based off the previous frame)

Those analysis files are then used to plan an edit timeline with an AI agent through API calls and skills. Currently it relies on OpenAI and a CLIP index to search for useful moments in the source content. The final timeline is rendered into an MP4 and made available in the dashboard for preview and download.

Minor alert/warning: it takes extremely long to run the program (eg multiple hours per finished video currently, mostly time spent on movie analysis)

## Overview

The code is split primarily into three big pieces, that are each fairly independent and can be ran/hosted individually.

`
web`

`api`

`api/prototyping`

The **web** portion of the codebase is a Next.js app written with TypeScript and Vanilla CSS. It can be hosted very simply to Vercel, with only the need for env variables for Clerk auth setup. The info pages don't require anything.

The **api** portion of the codebase is a FastAPI python application that primarily serves to store and send data. The functionality of the video content is very contained with a separate **requirements-modal.txt** as it is ran virtually on modal. Modal provides computers through it's SDK and API with $30 of free usage a month (main reason for the decision).  
During the development process, I found out that some of the video dependencies didn't have Windows wheels and I didn't feel it was worth it to swap my whole PC to linux for a project.  

The **api/prototyping** folder contains the independent workflows through which a video is analyzed. The code used in **api** was initially developed here and is now used for modular testing. 


## Running Locally

The project has separate dependency sets because the normal API, the frontend, and the heavier AI/video workflows do not all run in the same environment. Where they each reside is listed above in overview.

### Frontend

Ensure that you have Node/NPM installed to be able to install dependencies. Then, from the `web` directory:

```powershell
cd web
npm install
npm run dev
```
By default, the frontend expects the API to be running at http://127.0.0.1:8000

### Backend

The backend can be run from the repo root, or from the api folder. A virtual environment is strongly recommended.

```powershell
python -m venv api/.venv
. api/.venv/Scripts/Activate.ps1
pip install -r api/requirements.txt
```

Then start and check the API:

`python -m api.main`

`Invoke-RestMethod http://127.0.0.1:8000/healthz`

For the real upload/edit workflows, the API needs cloudflare R2 env variables, otherwise it will only be able to run local-only pieces. It can still run, however the dashboard will not be fully functional.

#### Modal

The heavier analysis and rendering workflows run through Modal, and thus require a package and auth.modal token new

Modal can be authenticated locally through:

`modal token new`




## Workflows

The workflow is pretty extensive and generally seeks quality > speed and cost (though this is cope to an extent). The goal was for this to be unique rather than a slop generator, and as such, every individual scene and frame of provided media is first analyzed deterministically, and likewise with audio files.

In order to create an edit:
 - Analyze audio workflow
 - Analyze footage workflow
 - Compose workflow
 - Render workflow

The workflows are all moderately similar to each in the fact that they have a deterministic step that converts the inputs into an easy to digest JSON file, that is stored for future use.
Compose takes specific shots of footage based on the audio analysis, eg factors such as BPM (tool would already be pretty cool with this only imo).

The analyze audio workflow also has an option youtube url download that does not currently work due to Youtube resetting cookies pretty frequently it seems

## Storage and Infrastructure

A variety of tradeoffs between cost and efficiency were once agian made here. The main issue was the storage of movies that were multiple gigabytes. The workaround was to use **Cloudflare R2 Object Storage** which is free with no egress costs, **Railway** for the FastAPI backend, **Clerk** for an auth solution, and **Vercel** for the frontend application. 

The alternative considered was Supabase - which would be a fair amount more expensive due to file storage, but would definitely be a solid choice as it is able to do pretty much everything, if someone wants to self-host.

## Future Improvements and Limitations

This is still very much an active project. The MVP currently works for fairly cheap and can be used to create moderately cool edits, but the workflow has a lot of potential vectors for improvement. Even the simple deterministic analyses could be improved on.

Current limitations include:

- uplaods current focus of WAV audio and MP4 video
- speed issues, especially on movie analysis and synthesis, can take a few hours
- no unique edit types, purely relies on what it's fed right now - in the future I want to add masks, layers, colour grading etc and turn it into a full-fledged editor

## AI Usage and Disclaimer

This repository did in fact have a fair amount of AI usage on it, primarily for the implementation of the backend. This was done responsibly however, with all higher-level decisions from libaries to structure to workflows decided by myself. Additionally, a lot of smaller fixes were done manually.

My AI workflow in particular - Claude Opus 4.6/7 for planning -> GPT 5.5 for writing code. The [superpowers](https://github.com/obra/superpowers) skill was used.


