"""Bounded streaming encoders. Files are decoded before they can be committed."""
import os
from pathlib import Path
from .models import digest


def validate(path,rate=24000):
    import soundfile as sf
    import numpy as np
    frames=0;peak=0.
    with sf.SoundFile(str(path)) as stream:
        if stream.samplerate!=rate or stream.channels!=1:raise ValueError('Audio sai sample rate/channel')
        # The bundled mpg123 can misdecode when a read splits an MP3 granule.
        # A multiple of 1152 also aligns MPEG-2's 576-sample granules, while
        # retaining bounded memory instead of decoding the whole file at once.
        blocksize=1152*56 if stream.format=='MP3' else 65536
        for block in stream.blocks(blocksize=blocksize,dtype='float32'):
            if not np.isfinite(block).all():raise ValueError('Audio chứa số không hữu hạn')
            frames+=len(block)
            if len(block):peak=max(peak,float(np.max(np.abs(block))))
    if not frames or peak<1e-5:raise ValueError('Audio rỗng hoặc hoàn toàn im lặng')
    return dict(sha256=digest(path),duration=frames/rate,rate=rate)


def encode(path,blocks,format='wav',rate=24000,bitrate=128):
    import numpy as np
    import soundfile as sf
    if format not in ('wav','mp3'):raise ValueError('Định dạng audio không hợp lệ')
    if bitrate not in (96,128,192):raise ValueError('Bitrate MP3 không hợp lệ')
    if format=='wav':
        with sf.SoundFile(str(path),'w',samplerate=rate,channels=1,format='WAV',subtype='PCM_16') as stream:
            for block in blocks:
                block=np.asarray(block,dtype=np.float32)
                if block.ndim!=1 or not np.isfinite(block).all():raise ValueError('Output engine không hợp lệ')
                stream.write(block)
    else:
        import lameenc
        encoder=lameenc.Encoder();encoder.set_bit_rate(bitrate);encoder.set_in_sample_rate(rate)
        encoder.set_channels(1);encoder.set_quality(2)
        with Path(path).open('wb') as stream:
            for block in blocks:
                block=np.asarray(block,dtype=np.float32)
                if block.ndim!=1 or not np.isfinite(block).all():raise ValueError('Output engine không hợp lệ')
                stream.write(encoder.encode((np.clip(block,-1,1)*32767).astype('<i2').tobytes()))
            stream.write(encoder.flush());stream.flush();os.fsync(stream.fileno())
    # Windows _commit requires a writable descriptor, even after a writer closed.
    with Path(path).open('r+b') as stream:stream.flush();os.fsync(stream.fileno())
    return validate(path,rate)
