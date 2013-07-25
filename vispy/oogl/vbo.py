# -*- coding: utf-8 -*-
""" Definition of Vertex Buffer Object class.

"""

from __future__ import print_function, division, absolute_import

import sys
import numpy as np

from vispy import gl
from . import GLObject, push_enable, pop_enable, ext_available

if sys.version_info > (3,):
    basestring = str

# Monkey-patch pyopengl to fix a bug in glBufferSubData
_m = sys.modules[gl.glBufferSubData.wrapperFunction.__module__]
_m.long = int


 # Data types that OpenGL ES 2.0 can understand
DTYPES =  {   'uint8':gl.GL_UNSIGNED_BYTE,    'int8':gl.GL_BYTE,
                'uint16':gl.GL_UNSIGNED_SHORT,  'int16':gl.GL_SHORT, 
                'float32':gl.GL_FLOAT, 
                'float16': gl.ext.GL_HALF_FLOAT }
                # GL_FIXED?



class Buffer(GLObject):
    """ The buffer is used to store vertex data. It is recommended to
    use one of the subclasses: VertexBuffer or ElementBuffer.
    """
    
    
    def __init__(self, target, data=None):
        
        # Store target (i.e. array buffer of index buffer)
        if target not in [gl.GL_ARRAY_BUFFER, gl.GL_ELEMENT_ARRAY_BUFFER]:
            raise ValueError("Invalid target for vertex buffer object.")
        self._target = target
        
        # Buffer ID (by which OpenGl identifies the texture)
        # 0 means uninitialized, <0 means error.
        self._handle = 0
        
        # Keep track of number of bytes in the buffer
        self._buffer_size = -1
        
        # Set data?
        if data is not None:
            self.set_data(data)
    
    
    def _create(self):
        self._handle = gl.glGenBuffers(1)
    
    def _delete(self):
       gl.glDeleteBuffers([self._handle])
    
    
    def __del__(self):
        self.delete()
    
    
    @property
    def nbytes(self):
        """ The number of bytes that the buffer uses.
        """
        return self._buffer_size
    
    
    def set_data(self, data, offset=None):
        """ Set the data for this buffer. If the size of the given data
        matches the current buffer size, the data is updated in a fast
        manner.
        
        Users typically do not use this class directly. The buffer class
        does not care about type of shape; it's just a collection of
        bytes. The VertexBuffer and ElementBuffer wrap the Buffer class
        to give meaning to the data.
        
        """
        
        # Check data
        if not isinstance(data, np.ndarray):
            raise ValueError("Data should be a numpy array.")
        
        # Reset if there was an error earlier
        if self._handle < 0:
            self._handle = 0
            self._buffer_size = 0
        
        # Check offset
        if offset is not None:
            assert (offset + data.nbytes) <= self._buffer_size
        elif data.nbytes == self._buffer_size:
            # If data is of same size, we can use glBufferSubData
            offset = 0
        
        # Set pending data, and number of bytes
        self._pending_data = data, offset
        self._buffer_size = data.nbytes
    
    
    def _upload(self, data):
        # todo: allow user to control usage (DYNAMIC_DRAW, STATIC_DRAW)
        gl.glBufferData(self._target, data.nbytes, data, gl.GL_DYNAMIC_DRAW)
    
    
    def _update(self, data, offset):
        # Probably faster than upload
        gl.glBufferSubData(self._target, offset, data.nbytes, data)
    
    
    def _enable(self):
        
        # Error last time?
        if self._handle < 0:
            return
        
        # Need to update data?
        if self._pending_data:
            data, offset = self._pending_data
            self._pending_data = None
            if offset is not None:
                # Fast update
                gl.glBindBuffer(self._target, self._handle)
                self._update(data, offset)
            else:
                # Recreate buffer object, just in case
                self.delete()
                self._create()
                # Upload data
                gl.glBindBuffer(self._target, self._handle)
                self._upload(data)
        
        # Bind
        gl.glBindBuffer(self._target, self._handle)
    
    
    def _disable(self):
        gl.glBindBuffer(self._target, 0)



class VertexBuffer(GLObject):
    """ Representation of vertex buffer object of type GL_ARRAY_BUFFER,
    which can be used to store vertex data. 
    
    To use a VertexBuffer, set it as a member of
    a_shader_program.attributes.
    """
    # When enabled,  pointer in gl.glVertexAttribPointer becomes an offset
    
    def __init__(self, data=None, buffer=None):
        
        # Whether this VertexBuffer is a view derived from another VertexBuffer
        self._isview = False
        
        # Set buffer
        if buffer is None:
            self._buffer = Buffer(gl.GL_ARRAY_BUFFER)
        elif isinstance(buffer, Buffer):
            self._buffer = buffer
        else:
            raise ValueError("Invalid buffer argument for VertexBuffer")
        
        # View parameters, in bytes. 
        self._offset = 0
        self._stride = 0
        
        # Data parameters
        self._shape = None
        self._type = None
        
        # Set data?
        if data is not None:
            self.set_data(data)
    
    
    def _enable(self):
        if self._buffer is not None:
            self._buffer._enable()
    
    def _disable(self):
        if self._buffer is not None:
            self._buffer._disable()
    
    
    @property
    def buffer(self):
        """ The underlying Buffer object. Note that multiple VertexBuffers
        can share one buffer object.
        """
        return self._buffer
    
    
    def set_data(self, data, offset=None):
        """ Set vertex attribute data, or a part of it. If the data
        matches the current size of the buffer, the data is updated
        faster.
        
        Parameters
        ----------
        data : numpy array
            The data to set. 
        offset : int
            The offset, to update part of the buffer. Optional.
        
        """
        
        # Can we update the data at all from this VertexBuffer?
        if self._isview:
            raise RuntimeError("Cannot set data from a view-VertexBuffer.")
        
        # Check data
        if not isinstance(data, np.ndarray):
            raise ValueError("Data should be a numpy array.")
        
        if data.dtype.fields:
            # Data with multiple fields
            fields = unravel_dtype_fields(data.dtype)
            for name, fieldinfo in fields.items():
                assert fieldinfo[0] in DTYPES
                assert fieldinfo[1] in (1,2,3,4)
            # Set type and shape
            self._type = fields
            self._shape = data.size, 1
        
        else:
            # Plain data
            tuple_count = 1
            assert data.ndim in (1,2)
            if data.ndim == 2:
                assert data.shape[1] in (1,2,3,4)
                tuple_count = data.shape[1]
            # Convert if necessary
            if not data.dtype.name in DTYPES:
                data = data.astype(np.float32)  
            # Set type and shape
            self._type = data.dtype.name
            self._shape = data.shape[0], tuple_count
        
        # Check offset
        if self._offset:
            offset = (offset or 0) + self._offset
        
        # Set data in buffer
        self._stride = data.dtype.itemsize * self._shape[1]
        self._buffer.set_data(data, offset)
    
    
    @property
    def view_params(self):
        """ A tuple with (offset, stride), specifying the slice in
        the Buffer object, in bytes.
        """
        return self._offset, self._stride
    
    
    @property
    def type(self):
        """ The name of the dtype of the data. If the data is a numpy array
        with fields, this yields a list of field specifiers.
        """
        return self._type
    
    
    @property
    def shape(self):
        """ The shape of the data that this VertexBuffer represents. This 
        is always a 2-element tuple (size, vector_size).
        """
        return self._shape
    
    
    def __getitem__(self, index):
        
        if isinstance(index, basestring):
            # Try to get field info
            if not isinstance(self._type, dict):
                raise RuntimeError('Cannot index by name in this VertexBuffer.')
            try:
                fieldinfo = self._type[index]
            except KeyError:
                raise ValueError('Invalid field name for this VertexBuffer.')
            # Get view params
            new_offset = fieldinfo[2] + self._offset
            new_stride = self._stride
            # Type and shape
            new_type = fieldinfo[0]
            new_shape0 = self._shape[0]
            new_shape1 = fieldinfo[1]  # number of elements
        elif isinstance(index, slice):
            # Get defaults
            start = (index.start or 0)
            step = (index.step or 1)
            stop = index.stop or self._shape[0]
            assert start >= 0
            assert step >= 1
            assert stop > 0
            # Get view params
            new_offset = start*self._stride + self._offset
            new_stride = step*self._stride
            # Type and shape
            new_type = self._type
            new_shape0 = (stop-start) // step
            new_shape1 = self._shape[1]
        else:
            raise ValueError('Invalid parameter for getting a view on a VertexBuffer.')
        
        # Create new VertexBuffer based on our own buffer
        newbuffer = VertexBuffer(buffer=self._buffer)
        newbuffer._isview = True
        
        # Set view parameters
        newbuffer._offset = new_offset
        newbuffer._stride = new_stride
        
        # Other parameters
        newbuffer._shape = new_shape0, new_shape1
        newbuffer._type = new_type
        
        # Done
        return newbuffer
    


class ElementBuffer(GLObject):
    """ Representation of vertex buffer object of type GL_ELEMENT_ARRAY_BUFFER,
    which can be used to store indices to vertex data. 
    
    To use an ElementBuffer, enable it before drawing.
    When enabled, the indices pointer in glDrawElements becomes a byte offset.
    """
    
    def __init__(self, data=None, buffer=None):
        
        # Set buffer
        if buffer is None:
            self._buffer = Buffer(gl.GL_ELEMENT_ARRAY_BUFFER)
        elif isinstance(buffer, Buffer):
            self._buffer = buffer
        else:
            raise ValueError("Invalid buffer argument for ElementBuffer")
        
        # Data parameters
        self._shape = None
        self._type = None
        
        # Set data?
        if data is not None:
            self.set_data(data)
    
    
    def _enable(self):
        if self._buffer is not None:
            self._buffer._enable()
    
    def _disable(self):
        if self._buffer is not None:
            self._buffer._disable()
    
    
    @property
    def buffer(self):
        """ The underlying Buffer object.
        """
        return self._buffer
    
    
    def set_data(self, data, offset=None):
        """ Set vertex element data, or a part of it. If the data
        matches the current size of the buffer, the data is updated
        faster.
        
        Parameters
        ----------
        data : numpy array
            The data to set. 
        offset : int
            The offset, to update part of the buffer. Optional.
        
        """
        
        # Check data
        if not isinstance(data, np.ndarray):
            raise ValueError("Data should be a numpy array.")
        
        # Plain data
        tuple_count = 1
        assert data.ndim in (1,2)
        if data.ndim == 2:
            assert data.shape[1] in (1,2,3,4)
            tuple_count = data.shape[1]
        # Convert if necessary
        if not data.dtype.name in DTYPES:
            data = data.astype(np.float32)  
        # Set type and shape
        self._type = data.dtype.name
        self._shape = data.shape[0], tuple_count
        
        # Set data in buffer
        self._buffer.set_data(data, offset)



def unravel_dtype_fields(dtype):
    """ Create a dictionary of names to tuples, one for each field in
    the given dtype: (dtypename, size, offset)
    """
    fields = {}
    for name in dtype.fields:
        type, offset = dtype.fields[name]
        if type.subdtype:
            thisdtype, shape = type.subdtype
        else:
            thisdtype, shape = type, (1,)
        assert len(shape) == 1
        fields[name] = thisdtype.name, shape[0], offset, 
    return fields
