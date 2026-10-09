"""One durable background worker; controls stay on the polling thread."""
from __future__ import annotations
import threading
import time
from .store import Store

_local=threading.local()

class Cancelled(RuntimeError): pass

def checkpoint():
    worker=getattr(_local,'worker',None)
    if worker and worker.cancelled(): raise Cancelled('Task cancelled; discard this result')

class Worker:
    def __init__(self, store, dispatch, log=lambda text:None):
        self.store,self.dispatch,self.log=store,dispatch,log
        self.stop=threading.Event();self.wake=threading.Event()
        self._lease = None
        self.thread=threading.Thread(target=self.run,daemon=True,name='bibliothecary-jobs')

    def start(self):
        import fcntl
        self._lease = (self.store.root / '.worker.lock').open('a')
        try:
            fcntl.flock(self._lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lease.close()
            raise RuntimeError('This library already has a background worker') from None
        self.store.recover()
        self.thread.start()

    @property
    def in_worker(self): return getattr(_local,'worker',None) is self

    def cancelled(self):
        key=getattr(_local,'job',None)
        if not key: return False
        with self.store.connect() as db:
            row=db.execute('SELECT status FROM jobs WHERE id=?',(key,)).fetchone()
        return self.stop.is_set() or not row or row[0]!='running'

    def submit(self,kind,data,key=None):
        result=self.store.enqueue(kind,data,key);self.wake.set();return result

    def run(self):
        try:
            self._run()
        finally:
            if self._lease: self._lease.close()

    def _run(self):
        _local.worker=self
        while not self.stop.is_set():
            job=self.store.claim()
            if job is None:
                self.wake.wait(1);self.wake.clear();continue
            _local.job=job['id'];start=time.monotonic()
            try:
                checkpoint();self.dispatch(job['kind'],job['data']);checkpoint()
                self.store.job_state(job['id'],'succeeded')
            except Cancelled: pass
            except Exception as err:
                self.store.job_state(job['id'],'uncertain' if getattr(err,'delivery_uncertain',False) else 'failed',str(err)[:500])
                self.log(f"Task {job['id']} failed: {type(err).__name__}; use /jobs and /retry")
            finally:
                self.store.put('timing',job['id'],{'kind':job['kind'],'seconds':round(time.monotonic()-start,3)})
                _local.job=None

    def close(self):
        self.stop.set();self.wake.set();self.thread.join(2)
