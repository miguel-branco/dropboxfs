#!/usr/bin/env python

from collections import defaultdict
from errno import ENOENT
from stat import S_IFDIR, S_IFLNK, S_IFREG
from sys import argv, exit
from time import time

from fuse import FUSE, FuseOSError, Operations, LoggingMixIn

import cStringIO
import time
import dateutil.parser
import os

import dropbox

class DropboxFS(LoggingMixIn, Operations):
    """Example memory filesystem. Supports only one level of files."""
    
    def __init__(self, token):
        self.dropbox = dropbox.client.DropboxClient(token)
        self.data = defaultdict(str)
        self.fd = 0

    def get_metadata(self, path):
        try:
            metadata = self.dropbox.metadata(path, list=False)
        except dropbox.rest.ErrorResponse as ex:
            if ex.status == 404:
                return None
            else:
                raise 
        else:
            return metadata

    def list_folder(self, path):
        # TODO: Change for 'delta' call to avoid 25,000 files limit
        metadata = self.dropbox.metadata(path, list=True)
        folders = []
        for entry in metadata['contents']:
            folders.append(os.path.split(str(entry['path']))[1])
        return folders

    def chmod(self, path, mode):
        return 0

    def chown(self, path, uid, gid):
        pass
    
    def create(self, path, mode):
        # TODO: 'mode' is ignored
        return self.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)

    def destroy(self, path):
        pass

    def flush(self, path, fh):
        return 0
    
    def fsync(self, path, datasync, fh):
        return 0
    
    def fsyncdir(self, path, datasync, fh):
        return 0
    
    def getattr(self, path, fh=None):
        metadata = self.get_metadata(path)
        if not metadata:
            raise FuseOSError(ENOENT)
        if 'modified' in metadata:
            mtime = int(time.mktime(dateutil.parser.parse(metadata['modified']).timetuple()))
        else:
            mtime = int(time.time())
        if metadata['is_dir']:
            return dict(st_mode=(S_IFDIR | 0755), st_nlink=1,
                st_size=metadata['bytes'], st_ctime=mtime, st_mtime=mtime, st_atime=mtime)
        else:
            return dict(st_mode=(S_IFREG | 0755), st_nlink=1,
                st_size=metadata['bytes'], st_ctime=mtime, st_mtime=mtime, st_atime=mtime)
    
    def getxattr(self, path, name, position=0):
        return ''
    
    def init(self, path):
        pass

    def link(self, target, source):
        self.dropbox.file_copy(source, target)

    def listxattr(self, path):
        return []
    
    def mkdir(self, path, mode):
        self.dropbox.file_create_folder(path)
    
    def mknod(self, path, mode, dev):
        raise FuseOSError(EROFS)

    def open(self, path, flags):
        try:
            f, metadata = self.dropbox.get_file_and_metadata(path)
        except dropbox.rest.ErrorResponse as ex:
            if ex.status == 404:
                rev = None
            else:
                raise
        else:
            rev = metadata['rev']

        if flags & os.O_CREAT or flags & os.O_TRUNC:
            nf = cStringIO.StringIO()
            self.dropbox.put_file(path, nf, overwrite=True, parent_rev=rev)
        elif rev:
            nf = cStringIO.StringIO(f.read())
        else:
            raise FuseOSError(ENOENT)

        self.data[path] = {'f': nf, 'rev': rev}
        self.fd += 1
        return self.fd
    
    def opendir(self, path):
        self.fd += 1
        return self.fd

    def read(self, path, size, offset, fh):
        f = self.data[path]['f']
        f.seek(offset)
        return f.read(size)
    
    def readdir(self, path, fh):
        return ['.', '..'] + self.list_folder(path)
    
    def readlink(self, path):
        with self.dropbox.get_file(path) as f:
            return f.read()

    def release(self, path, fh):
        f = self.data[path]['f']
        rev = self.data[path]['rev']
        f.seek(0)
        self.dropbox.put_file(path, f, overwrite=True, parent_rev=rev)
    
    def releasedir(self, path, fh):
        pass

    def removexattr(self, path, name):
        pass
    
    def rename(self, old, new):
        self.dropbox.file_move(old, new)
    
    def rmdir(self, path):
        self.dropbox.file_delete(path)
    
    def setxattr(self, path, name, value, options, position=0):
        pass
    
    def statfs(self, path):
        return dict(f_bsize=512, f_blocks=4096, f_bavail=2048)
    
    def symlink(self, target, source):
        self.dropbox.file_copy(source, target)
    
    def truncate(self, path, length, fh=None):
        f, metadata = self.dropbox.get_file_and_metadata(path)
        data = f.read(length)
        if len(data) < length:
            pad = '\0' * (length - len(data))
        else:
            pad = ''
        nf = cStringIO.StringIO(data + pad)
        self.dropbox.put_file(path, nf, overwrite=True, parent_rev=metadata['rev'])
    
    def unlink(self, path):
        pass
    
    def utimens(self, path, times=None):
        pass
    
    def write(self, path, data, offset, fh):
        f = self.data[path]['f']
        f.seek(offset)
        f.write(data)
        return len(data)

if __name__ == "__main__":
    if len(argv) != 3:
        print 'usage: %s <token> <mountpoint>' % argv[0]
        exit(1)

    token = argv[1]
    mountpoint = argv[2]
    fuse = FUSE(DropboxFS(token), mountpoint, foreground=True)