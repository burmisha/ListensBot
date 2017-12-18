# ListensBot

```bash
# 1. Go to root of this repo
cd ListensBot

# 2. Create secrets.json
echo '{
    "SoundcloudToken": "your_api_token",
    "DownloadPath": ["home", "user", "some", "path"]
}' > secrets.json

# 3. Install ffmpeg, missing modules and set up virtualenv
brew install ffmpeg
virtualenv 'venv' # run once
. ./venv/bin/activate
pip install soundcloud
pip install six
pip install eyeD3
pip install mutagen
pip install pafy
pip install lxml
deactivate

# 4. Run script
. ./venv/bin/activate
export PAFY_BACKEND=internal # just to disable warning from pafy
./download.py --help
./download.py \
  --openuni \
  --shlosberg-live \
  --soundcloud \
  --save
deactivate
```
