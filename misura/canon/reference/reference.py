# -*- coding: utf-8 -*-
"""Option persistence on HDF files."""
import numpy as np
#TODO: Unify commit/append!!! They are basically the same!

# Functions can be pickled only if defined as top-level in a module	
def decode_time(node,index):
	return node[index][0]


class Reference(object):
	"""Reference to a location on an output file, 
	methods for creating it 
	and for committing new data."""
	unbound={'decode_time':decode_time}
	mtime=0
	"""Last modified time"""
	summary=False
	"""Interpolated mirror"""
	def __init__(self,outfile,folder=False,opt=False,write_current=False):
		"""If `opt` is False, an existing reference is red from the outfile at the requested path.
		Otherwise, a new reference is created following `opt` dictionary-like object.
		"""
		self.summary=False
		self.mtime=0
		self._path=False
		"""Path of the output node"""
		self.outfile=outfile
		"""Output SharedFile"""
		self.write_current=write_current
		# Define static methods for unbound functions
		for k,func in self.unbound.iteritems():
			setattr(self,k,staticmethod(func))
		# Create or Read a reference
		if opt is False:
			self.open(folder)		
		else:
			# get folder from KID if undefined
			if folder is False:
				folder=opt['kid']
				h=opt['handle']
				if folder.endswith(h):
					folder=folder[:-len(h)]
			if not folder.endswith('/'): 
				folder+='/'
			self.folder=folder
			"""Folder path where data will be saved"""
			self.opt=opt
			self.create()
			
	@property
	def path(self):
		return self._path
	
	@path.setter
	def path(self,new):
		self._path=new
		self.set_attributes()
		
	def __len__(self):
		return self.outfile.len(self.path)
		
	@property
	def handle(self):
		"""Shortcut for getting the Option handle (output entity path)"""
		return self.opt['handle']
	
	@property
	def name(self):
		"""Shortcut for getting the Option name (output entity title)"""
		return self.opt['name']
		
	def create(self):
		"""Creates the data structure on the output file.
		Returns the folder into which the data was created. 
		Returns False if the structure was already present.
		To be overridden."""
		ref=self.folder+self.handle
# 		print 'creating reference node',ref
		if self.outfile.has_node(ref):
			if self.outfile.get_node_attr(ref,'_reference_class')==self.__class__.__name__:
# 				print 'Recovered previous reference',ref
				self.path=ref
				return False
			print 'Removing wrong type old reference',ref
			self.outfile.remove_node(ref)
		if self.folder!='/' and self.folder.endswith('/'):
			return self.folder[:-1]
		return self.folder
	
	def open(self,folder):
		"""Opens an existing data structure located at `folder`"""
		f=folder.split('/')
		if f[-1]=='': f.pop(-1)
		hnd=f.pop(-1)
		self.folder='/'.join(f)+'/'
		self._path=self.folder+hnd
		print 'opening existent node',folder,self.folder,self.path
		self.opt=self.get_attributes()	
		
	def append(self,data):
		"""Append rows of data to referenced node."""
		return self.outfile.append_to_node(self.path,data)
	
	def set_attributes(self):
		if not self.outfile.has_node(self.path):
			print 'ERROR: NO NODE!',self.path
			return False
# 		print 'set_attributes',self.opt.keys()
		ks=self.opt.keys()
		if not self.write_current:
			for k in ['current','factory_default']:
				if k in ks: 
					ks.remove(k)
		for key in ks:
			self.outfile.set_node_attr(self.path, key, self.opt[key])
		# Remember reference class type
		self.outfile.set_node_attr(self.path,'_reference_class',self.__class__.__name__)
		return True	
	
	def get_attributes(self):
		return self.outfile.get_attributes(self.path)
	
	@classmethod
	def encode(cls,t,dat):
		return np.array([t]+dat)
	
	@classmethod
	def decode(cls,dat):
		dat=list(dat)
		if len(dat)==1:
			dat=list(dat[0])
		return [dat[0],dat[1:]]
	
	def __getitem__(self,idx_or_slice):
		if isinstance(idx_or_slice,int):
			return self.decode(self.outfile.col_at(self.path,idx_or_slice,raw=True))
		return map(self.decode,self.outfile.col(self.path,idx_or_slice,raw=True))
	
	def time_at(self,idx=-1):
		"""Returns the time label associated with the last committed point"""
		t=self.outfile.get_decoded(self.path,idx,get=self.unbound['decode_time'])
		return t
	
	def get_time(self,t):
		"""Finds the nearest row associated with time `t`"""
		idx=self.outfile.get_time(self.path, t, get=self.unbound['decode_time'])
		return idx
	
	def commit(self,data):
		"""Encode data and write it onto the reference node."""
# 		print 'committing',self.path,data
		# Cut too old points
		n=0
		for td in data:
			if td is False: 
				continue
			t,dat=td
			app=self.encode(t,dat)
			if app is None: 
				continue
			self.append(app)
			n+=1
# 			self.mtime=t
		return n
	
# 	def append_from_sequence(self,filepath):
# 		return self.outfile.append_from_sequence(self.path,filepath,self.__class__)
	
	#DEPRECATED
	def copy(self,destpath,startTime=-1,endTime=-1,stats=False):
		"""Create an identical reference object on `destpath` SharedFile instance 
		and copy data from time `startTime` to time `endTime`.
		Return written destination reference."""
		N=len(self)
		if N<=0:
			print 'no points in reference',self.path
			return False
		### Calc start index
		if startTime<=0: 
			startIdx=0
		else:
			tN=self.time_at(-1)
			if startTime>=tN:
				print 'no points in range start',self.path,startTime,tN,self[-1]
				return False
			print 'getting start time',startTime
			startIdx=self.get_time(startTime)
		### Calc end index
		if endTime<=0:
			endIdx=N-1
		else:
			t0=self.time_at(0)
			if endTime<=t0:
				print 'no points in range end',self.path,endTime,t0,self[0]
				return False
			print 'getting end time',endTime
			endIdx=self.get_time(endTime)+1
		if endIdx>=N-1: endIdx=N-1
		print 'start,end',self.path,startIdx,startTime,endIdx,endTime
		if endIdx<=startIdx:
			print 'erroneous range',self.path,startIdx,endIdx
			return False
		
		print 'copy',self.path,self.folder,startIdx,endIdx
		# Copy to destination path
		stats=self.outfile.leaf_copy(destpath, self.path, startIdx, endIdx,stats)
# 		dest=self.__class__(destfile,self.folder,self.opt)
# 		#TODO: optimized copy!
# 		print 'writing %i points onto %s' % (endIdx-startIdx+1,dest.path)
# 		dest.commit(self[startIdx:endIdx])
		return stats

	#TODO: move into OutputFile to avoid IPC
	def interpolate(self,step=1):
		"""Synchronize the internal interpolated summary reference. 
		Returns False if no summary is defined, or the time vector for interpolation"""
		# Nothing to interpolate
		if self.summary is False:
#			print 'No summary defined',self.path
			return False
		if len(self)<10:
#			print 'Not enough data',self.path,len(self)
			return False
		self.outfile.set_time_limit(0,-1)
		last=self[-1]
		if len(self.summary)==0:
			# No summary: start from the first point in self
			lsumt=int(self[0][0])+step
		else:
			# From the last summarized point
			lsumt=self.summary[-1][0]
		# Not enough data to calculate a new point
		dt=last[0]-lsumt
		if dt<=step*3:
#			print 'Not enough step',dt,self.path
			return False
		# Time sequence
		vt=np.arange(lsumt+step,last[0],step)[:-1]
		if len(vt)==0:
			print 'Time length is null',self.path
			return False
		return vt

