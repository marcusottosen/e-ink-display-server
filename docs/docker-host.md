# Home e-ink display host

## What this is

The Docker host is the local web tool for one fixed e-ink display. It stores
images, resizes them for the panel, keeps albums, and exposes HTTP endpoints for
the Pi. It controls that one panel.

## Pi connection

The Pi makes HTTP requests to the Docker host:

1. Ask whether a newer image is available.
2. Download the prepared PNG when there is one.
3. Tell the host when it starts, completes, or fails a refresh.

The host does not connect to the Pi. Configure the Pi separately with this
Docker host's LAN address and published port. There is no Pi IP address or Pi
listening port to configure here.

Plain HTTP with optional device-token authentication is intended for a private
home network. There is no web login or user-account system.

## Storage and restart behaviour

The host stores its SQLite database, originals, previews, and prepared files in
the `inky-host-data` Docker volume mounted at `/var/lib/inky`.

The volume survives host-container restarts and LXC restarts. The Compose service
uses `restart: unless-stopped`. Data is only removed by an explicit Docker-volume
removal or an LXC snapshot rollback.

Gallery deletion is permanent. Deleting an image removes its original file,
generated files, album entries, and queued job entries. It does not stop a
deletion because the image was used by an album or display request.

## Image handling

The fixed panel is 800 × 480. Its physical landscape/portrait installation and
rotation are set in the Settings page.

On the dashboard, selecting a file only opens it in the browser for the framing
helper. The file is not sent to the host until **Save to gallery** or **Upload and
display now** is pressed.

The host performs only these changes:

- Read EXIF orientation.
- Rotate the image when requested.
- Crop, fit with white borders, or stretch.
- Resize to the panel dimensions.

Colours are left alone. The Inky driver maps pixels to the panel when it performs
the physical refresh.

## Web pages

### Dashboard

Pick one image and use the framing helper before saving it or sending it to the
panel. The page also shows the last image confirmed by the Pi and which album is
running, if any. It also shows the newest image available to the Pi separately,
so it is clear when an image has been requested but not yet confirmed on the
panel. Sending one image directly stops the active album and drops its unfinished
image requests.

### Gallery

Shows stored images. Use **Edit** to choose each image's crop/fit/stretch and
rotation with the same panel-shaped helper used for a new upload. Those settings
are kept with that image and apply whether it is displayed on its own or from an
album.

Select one or more images and use **Play selected** to run a temporary playlist.
Choose the order and minutes per image; it is not added to the saved album list.
Use **Stop playback** on the dashboard to stop either a saved album or this
temporary playlist. Images can also be sent to the display or permanently
deleted, one at a time or in a selected group.

### Albums

Albums are playlists for the single display. They can run in order or shuffled,
with an interval per image. New albums start with a 20-minute interval.

Use **Add images** from the playlist while creating or editing an album. It opens
a searchable gallery picker, ordered newest first, which loads more images while
you scroll. New files can also be uploaded directly from that picker. They first
open the same local framing and rotation helper and are not uploaded until
**Add to album** is pressed.

There are no schedule windows, calendars, or multiple-display targets.

### Settings

Stores panel orientation/rotation and the optional device-token requirement.
The Pi's server URL and polling intervals belong in the Pi's own configuration.

## Main routes

```text
POST /api/v1/assets
PATCH /api/v1/assets/{asset_id}
GET  /api/v1/assets?query=&offset=&limit=
GET  /api/v1/assets/{asset_id}/original
DELETE /api/v1/assets/{asset_id}
POST /api/v1/assets/bulk-delete
GET  /api/v1/assets/{asset_id}/preview

POST /api/v1/albums
GET  /api/v1/albums
PATCH /api/v1/albums/{album_id}
PUT  /api/v1/albums/{album_id}/items
POST /api/v1/albums/{album_id}/run
POST /api/v1/albums/{album_id}/stop
DELETE /api/v1/albums/{album_id}

POST /api/v1/displays/inky-main/display-now
POST /api/v1/displays/inky-main/play-selection
POST /api/v1/displays/inky-main/stop-playback
GET  /api/v1/displays/inky-main/desired
GET  /api/v1/artifacts/{sha256}
POST /api/v1/displays/inky-main/heartbeat
POST /api/v1/displays/inky-main/jobs/{job_id}/started
POST /api/v1/displays/inky-main/jobs/{job_id}/completed
POST /api/v1/displays/inky-main/jobs/{job_id}/failed
```
