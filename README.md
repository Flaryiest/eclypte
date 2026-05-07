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

The **api** portion of the codebase is a FastAPI 