"""Real codec regression, synthetic signal only, no model or network."""
import json
import subprocess
import sys
import numpy as np
import soundfile as sf
from transcomic.tts.audio import encode


def test_long_mp3_validation_has_no_decoder_error_and_matches_full_decode(tmp_path):
    rate=24000
    t=np.arange(rate*12,dtype='float64')/rate
    noise=np.random.default_rng(17).normal(0,.12,len(t)).astype('float32')
    filtered=np.convolve(noise,np.ones(9)/9,mode='same').astype('float32')
    signal=((.22*np.sin(2*np.pi*201*t)+filtered)*(np.sin(2*np.pi*2.3*t)>0)).astype('float32')
    path=tmp_path/'âm thanh dài.mp3'
    encoded=encode(path,[signal],'mp3',rate=rate)
    full,actual_rate=sf.read(path,dtype='float32')
    assert actual_rate==rate and np.isfinite(full).all()
    code='import json,sys;from transcomic.tts.audio import validate;print(json.dumps(validate(sys.argv[1])))'
    result=subprocess.run([sys.executable,'-c',code,str(path)],capture_output=True,text=True,timeout=15)
    assert result.returncode==0 and not result.stderr,result.stderr
    checked=json.loads(result.stdout)
    assert checked['sha256']==encoded['sha256'] and checked['duration']==len(full)/rate
