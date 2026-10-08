# Local browser assets

Pages serve these assets from the tracker so loading a page does not send a
visitor's IP address or request metadata to a CDN or font provider.

| Component | Version | License |
| --- | --- | --- |
| Bootstrap CSS and bundled JavaScript | 5.3.8 | MIT, `bootstrap/LICENSE` |
| Bootstrap Icons CSS and fonts | 1.13.1 | MIT, `bootstrap-icons/LICENSE` |
| Inter variable font | 4.1 | SIL OFL, `inter/LICENSE.txt` |

`manifest.json` records pinned upstream URLs and SHA-256 checksums. Bootstrap
downloads were also checked against the SHA-384 integrity values in its official
documentation. Keep upstream assets and their licenses together when updating.
Run the browser privacy and navigation tests after an update. Do not edit the
vendored minified files as application source.
