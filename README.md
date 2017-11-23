# ListensBot

```bash
# 1. Go to root of this repo
cd ListensBot

# 2. Create secrets.json
echo '{
    "SoundcloudToken": "your_api_token",
    "DownloadPath": ["home", "user", "some", "path"]
}' > secrets.json

# 3. Install missing modules and run via virtualenv
virtualenv 'env' # run once
. ./env/bin/activate
pip install soundcloud
pip install six
pip install eyeD3
pip install mutagen
pip install pafy
export PAFY_BACKEND=internal # just to disable warning from pafy
./download.py --help
deactivate
```
