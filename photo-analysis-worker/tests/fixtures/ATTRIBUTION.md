# Test fixture attribution

`nasa_official_portrait.jpg` is a resized (longer side 900px, re-encoded as JPEG) copy of
["Official portrait of astronaut Linda M. Godwin"](https://commons.wikimedia.org/wiki/File:Official_portrait_of_astronaut_Linda_M._Godwin.jpg),
credited to NASA. Per Wikimedia Commons' metadata for that file: **public domain** (work
of a NASA employee/contractor made in the course of official duties - `PD-USGov-NASA`),
attribution not required, not copyrighted.

Used here only as a real photograph of a face to test `face_quality.py`'s detection path
(see `test_face_quality.py`) - resized down from the ~5200x6500px original for repo size,
which also happens to be a real-world case this feature needs to handle: `score_face_quality`
downscales large images before detection anyway (see its module docstring).
