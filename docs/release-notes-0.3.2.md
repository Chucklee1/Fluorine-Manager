## Fluorine Manager 0.3.2

### Highlights

- Renamed the rolling `beta` update channel to **Nightly**. Existing beta
  installations migrate automatically.
- Added a visible update prompt with **Install & restart**, **View release**,
  and **Later** actions.
- Nightly builds now use ordered build numbers, while tagged stable builds
  embed and validate the exact release version.
- Fixed FOMOD installers reading stale, differently-cased XML and image files
  left by previous installations. Each installation now uses a private
  temporary extraction directory that is removed afterward.

### Thanks

- [@DalenPlanestrider](https://github.com/DalenPlanestrider) reported and
  thoroughly diagnosed the FOMOD extraction collision in
  [#139](https://github.com/SulfurNitride/Fluorine-Manager/issues/139).
