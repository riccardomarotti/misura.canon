#!/usr/bin/python
# -*- coding: utf-8 -*-
"""
API for common data operations on local or remote HDF files.
"""

from scipy.interpolate import UnivariateSpline, interp1d
import numpy as np
import functools
import numexpr as ne
from .. import csutil
from ..csutil import lockme
from .. import reference
ne.set_num_threads(8)


class DataOperator(object):
    _zerotime = -1

    @property
    def zerotime(self):
        """Time at which the acquisition stats.
No data will be evaluate if older than zerotime."""
        if self.test is False:
            return 0
        if self._zerotime < 0:
            print 'ask zerotime'
            if not self.has_node('/conf'):
                print 'NO CONF NODE'
                return 0
            self._zerotime = self.get_node_attr('/conf', 'zerotime')
        return self._zerotime

    def get_zerotime(self):
        print 'get_zerotime'
        return self.zerotime

    def _xy(self, path=False, arr=False):
        """limit: limiting slice"""
        x = False
        node = False
        if path is not False:
            node = self._get_node(path)
            arr = node
            x = arr.cols.t
            y = arr.cols.v
        else:
            x = arr[:, 0]
            y = arr[:, 1]
        if len(arr) == 0:
            print 'Empty dataset', path
            return False, False
        if x is False:
            return False, False
        return x, y

    @lockme
    def col(self, path, idx_or_slice=None, raw=False):
        """Reads an array in the requested slice. If an integer index is specified, reads just one point."""
        path = self._versioned(path)
        n = self._get_node(path)

        # Convert to regular array (we could convert to dict for fields?)
        if not raw:
            try:
                n = n[:].view(np.float64).reshape(n.shape + (-1,))
            except:
                print 'SHAPE', path, n.shape
                raise

        if idx_or_slice is not None:
            slc = csutil.toslice(idx_or_slice)

            n = n[slc]
        return n

    def _col_at(self, path, idx, raw=False):
        """Retrive single index `idx` from node `path`"""
        node = self._get_node(path)
        n = node[idx]
        if not raw:
            n = n[:].view(np.float64).reshape(n.shape + (-1,))
        return n

    @lockme
    def col_at(self, *a, **k):
        """Retrive single index `idx` from node `path`, locked"""
        return self._col_at(*a, **k)

    def clean_start(self, g, start):
        # FIXME: Cut start limit. Send bug to pytables
        while len(g) > 0:
            if g[0] < start:
                g.pop(0)
                continue
            break
        return g

    def find_nearest_cond(self, tab, s, f=2., start_time=0, end_time=np.inf):
        """Search for the nearest value to `s` in table `tab`,
        by iteratively reducing the tolerance by a factor of `f`."""
        start_index = self._get_time(path, start_time)
        end_index = self._get_time(path, end_time)
        # Try exact term
        g = tab.get_where_list('v==s', stop=end_index)
        g = self.clean_start(g, start_index)
        if len(g) > 0:
            return g[0]

        ur = max(tab.cols.v) - s  # initial upper range
        lr = s - min(tab.cols.v)  # initial lower range
        last = None

        while True:
            # Tighten upper/lower ranges
            ur /= f
            lr /= f
            g = tab.get_where_list('((s-lr)<v) & (v<(s+ur))', stop=end_index)
            # Found!
            if g is None or len(g) == 0:
                if last is None:
                    return None
                return last[0]
            # FIXME: Cut start limit
            while True:
                if len(g) == 0:
                    if last is None:
                        return None
                    return last[0]
                if g[0] < start_index:
                    g.pop(0)
                    continue
                break
            # Save for next iter
            last = g
            if ur + lr < 0.0000000001:
                return None

    @lockme
    def search(self, path, op, cond='x==y', pos=-1, start_time=0, end_time=-1):
        """Search dataset path with operator `op` for condition `cond`"""
        print 'searching in ', path, cond
        tab = self._get_node(path)
        x, y = tab.cols.t, tab.cols.v
        y, m = op(y)
        if start_time == 0:
            start_index = 0
        else:
            start_index = self._get_time(path, start_time)
        if end_time == -1:
            end_index = len(y)
        else:
            end_index = self._get_time(path, end_time)
        last = -1
        # Handle special cases
        if cond == 'x>y':  # raises
            if y[0] > m:
                last = 0
            elif max(y) < m:
                return False
            cond = 'y>m'
        elif cond == 'x<y':  # drops
            if y[0] < m:
                last = 0
            elif min(y) > m:
                return False
            cond = 'y<m'
        elif cond == 'x~y':
            last = self.find_nearest_cond(
                tab, m, limit=slice(start_index, end_index))
            if last is None:
                return False
        else:
            cond = 'y==m'

        if last < 0:
            last = list(tab.get_where_list(cond, stop=end_index))
            last0 = last[:]
            # WARNING: start selector is not working.
            # TODO: Send bug to pytables!
            while start_index:
                if len(last) == 0:
                    last = None
                    break
                if last[0] < start_index:
                    last.pop(0)
                    continue
                break

            if last is None or len(last) == 0:
                print 'DataOps.search FAILED', path, cond, start_index, end_index, m, len(y), last0, last
                return False
            last = last[0]

        return last, x[last], y[last]

    def max(self, path):
        op = lambda y: (y, max(y))
        return self.search(path, op, cond='x==y')

    def min(self, path):
        op = lambda y: (y, min(y))
        return self.search(path, op, cond='x==y')

    def nearest(self, path, val):
        op = lambda y: (y, val)
        return self.search(path, op, cond='x~y')

    def equals(self, path, val, tol=10**-12):
        op = lambda y: (y, val)
        r = self.search(path, op)
        if not r:
            return False
        i, xi, yi = r
        if abs(yi - val) > tol:
            return False
        return i, xi, yi

    def drops(self, path, val, start_time=0):
        cond = 'x<y'
        op = lambda y: (y, val)
        print 'drops', path, val
        return self.search(path, op, cond, pos=0, start_time=start_time)

    def rises(self, path, val, start_time=0):
        #		cond=lambda a,b: a>b
        cond = 'x>y'
        op = lambda y: (y, val)
        print 'rises', path, val
        return self.search(path, op, cond, pos=0, start_time=start_time)

    def _get_time(self, path, t, get=False, seed=None):
        """Optimized search of the nearest index to time `t` using the getter function `get` and starting from `seed` index."""
        n = self._get_node(path)
        if get is False:
            get = lambda i: n[i][0]
        else:
            get = functools.partial(get, n)
        idx = csutil.find_nearest_val(n, t, get=get, seed=seed)

        return idx

    @lockme
    def get_time(self, *a, **k):
        return self._get_time(*a, **k)

    @lockme
    def get_time_profile(self, path, t):
        return self._get_time(path, t, get=reference.Profile.unbound['decode_time'])

    @lockme
    def get_time_image(self, path, t):
        return self._get_time(path, t, get=reference.Image.unbound['decode_time'])

    @lockme
    def spline_col(self, path=False, startIdx=0, endIdx=-1, time_sequence=[0], arr=False, k=3):
        """Returns a 1D interpolated version of the array, as per """
        x, y = self._xy(path, arr)
        if x is False:
            return False
        print 'building spline', path
        f = UnivariateSpline(x, y, k=k)
        print 'interp'
        r = f(time_sequence)
        return r

    @lockme
    def interpolated_col(self, path=False, startIdx=0, endIdx=None, time_sequence=[0], arr=False, kind='cubic'):
        x, y = self._xy(path, arr)
        if x is False:
            return False
        if startIdx == endIdx == -1:
            # Detect from time_sequence
            startIdx = self._get_time(path, time_sequence[0] - 1)
            endIdx = self._get_time(path, time_sequence[-1] + 1, seed=startIdx)
        s = slice(startIdx, endIdx)
        print 'Interpolating ', path, s
        f = interp1d(x[s], y[s], kind=kind, bounds_error=False, fill_value=0)
        print 'interp'
        r = f(time_sequence)
# 		print 'interpolate',x,time_sequence,r
        return r
