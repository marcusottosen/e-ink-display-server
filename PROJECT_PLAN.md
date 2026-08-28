# Inky home display tool — notes

## Scope

This is one home-use tool for one fixed e-ink display.

- The Docker host uses SQLite and its persistent Docker volume.
- One Raspberry Pi polls the host over the home network.
- The display model, size, and connection target are fixed configuration.
- The host does not need a Pi IP address or make connections to the Pi.
- The scope is SQLite, one display, and the functions listed below.
- The host only frames, rotates, and resizes an image. The panel driver handles
  the panel's own colour limitations when it refreshes.

## Project folders

```text
apps/host/          Web UI, API, image resize, SQLite state
apps/pi-agent/      Pi polling service and local downloaded-image cache
packages/contract/  Shared host/Pi request models
deploy/docker/      Docker host configuration
deploy/systemd/     Pi service files and install script
```

## Implemented

- [x] Docker host with a persistent named volume and automatic restart.
- [x] SQLite storage for images, albums, display jobs, and simple activity history.
- [x] Fixed 800 × 480 display settings with landscape/portrait rotation.
- [x] Dashboard image picker with local-only framing preview before upload.
- [x] Image gallery with permanent single and bulk deletion.
- [x] Per-image framing and rotation editor, used for gallery images and direct album uploads.
- [x] Album creation/editing, ordered or shuffled playback, and a 20-minute default interval.
- [x] Temporary playback for selected gallery images, with order, interval, and dashboard stop control.
- [x] Direct display actions stop the running album and cancel its unfinished image requests.
- [x] Searchable paged gallery picker for adding images to an album, including direct upload.
- [x] Pi-pull image delivery, status acknowledgements, and local Pi image cache.
- [x] Dashboard indication of the Pi-confirmed current image and active album.
