# Eclypte  
A multipurpose AI video editing pipeline. Hosted version can be found here: [https://eclypte.vercel.app/](https://eclypte.vercel.app/)

Initially created this project in order to create short-form content (particularly cool anime/movie edits) but the infrastructure works arguably better for normal editing activities, at least until I develop it more.


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

## Workflows

The workflow is pretty extensive and generally seeks quality > speed and cost (though this is cope to an extent). The goal was for this to be unique rather than a slop generator, and as such, every individual scene and frame of provided media is first analyzed deterministically, and likewise with audio files.
