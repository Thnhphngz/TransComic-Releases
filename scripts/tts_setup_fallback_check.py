"""Real automatic embedded GPU setup, or injected GPU failure -> real CPU."""
import argparse
import json
from pathlib import Path
import sys
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--runtime',required=True);p.add_argument('--models',required=True);p.add_argument('--gpu-success',action='store_true');args=p.parse_args()
    from scripts.test_runtime import outside
    import transcomic.tts.setup as module
    from transcomic.tts.models import ModelManager
    from transcomic.tts.managed_runtime import ManagedRuntimes
    import httpx
    root=outside(Path(args.root).absolute());root.mkdir(parents=True,exist_ok=False);packs=ManagedRuntimes(args.runtime);original=packs.install
    def install(backend,*a,**k):
        if backend=='CUDAExecutionProvider' and not args.gpu_success:raise RuntimeError('Injected CUDA preparation failure')
        return original(backend,*a,**k)
    packs.install=install;module.diagnostics=lambda:dict(compatible=False,missing=['onnxruntime'],providers=[],runtimes=[]);stages=[]
    try:
        with httpx.Client(transport=httpx.MockTransport(lambda r:(_ for _ in ()).throw(AssertionError('Verified cache must avoid HTTP')))) as client:
            result=module.SetupFlow(root,ModelManager(args.models),packs).run(dict(variant='standard',voice='af_heart',speed=1,language='en-us'),threading.Event(),lambda a,b,s:stages.append(s),client)
        assert result['backend']==('CUDAExecutionProvider' if args.gpu_success else 'CPUExecutionProvider')
        assert module.prefer_cpu(root,packs)==(not args.gpu_success)
        if args.gpu_success:assert result['engine_process']['gpu_verified'] and result['engine_process']['gpu_nodes']>0
        assert 'Runtime' in result['engine_process']['executable'] and '.venv' not in result['engine_process']['executable']
        result.update(gpu_failure_injected=not args.gpu_success,cpu_inference_real=not args.gpu_success,gpu_inference_real=args.gpu_success,negative_cache=not args.gpu_success,bootstrap_ort_missing_injected=True,no_http=True,stages=stages)
        (root/'report.json').write_text(json.dumps(result,ensure_ascii=True,indent=2),encoding='utf8');print(json.dumps(result,ensure_ascii=True))
    except BaseException:
        import traceback
        (root/'failure.txt').write_text(traceback.format_exc(),encoding='utf8');raise

if __name__=='__main__':main()
