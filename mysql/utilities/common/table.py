#
# Copyright (c) 2010, Oracle and/or its affiliates. All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; version 2 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307 USA
#

"""
This module contains abstractions of a MySQL table and an index.
"""

#import datetime
#import optparse
#import os
import re
#import time
import MySQLdb
from mysql.utilities.common import MySQLUtilError

# List of database objects for enumeration
DATABASE, TABLE, VIEW, TRIGGER, PROC, FUNC, EVENT, GRANT = "DATABASE", \
    "TABLE", "VIEW", "TRIGGER", "PROCEDURE", "FUNCTION", "EVENT", "GRANT"

def _parse_object_name(qualified_name):
    """Parse db, name from db.name
    
    qualified_name[in] MySQL object string (e.g. db.table)
                       
    Returns tuple containing name split
    """

    parts = re.match("(\w+)(?:\.(\w+))?", qualified_name)
    if parts:
        return parts.groups()
    else:
        return (None, None)

class Index(object):
    """
    The Index class encapsulates an index for a given table as defined by
    the output of SHOW INDEXES FROM. The class has the following
    capabilities:

        - Check for duplicates
        - Create DROP statement for index
        - Print index CREATE statement
    """   
    
    def __init__(self, db, index_tuple, verbose=False):
        """Constructor
        
        db[in]             Name of database
        index_tuple[in]    A tuple from the get_tbl_indexes() result set
        verbose[in]        print extra data during operations (optional)
                           default value = False
        """

        # Initialize and save values
        self.db = db
        self.verbose = verbose
        self.columns = []
        self.table = index_tuple[0]
        self.unique = not index_tuple[1]
        self.name = index_tuple[2]
        col = (index_tuple[4], index_tuple[7])
        self.columns.append(col)
        self.type = index_tuple[10]
        self.compared = False                    # mark as compared for speed
        self.duplicate_of = None                 # saves duplicate index
        if index_tuple[7] > 0:
            self.column_subparts = True          # check subparts e.g. a(20)
        else:
            self.column_subparts = False
        
    def __cmp_columns(self, col_a, col_b):
        """Compare two columns on name and subpart lengths if present

        col_a[in]          First column to compare
        col_b[in]          Second column to compare

        Returns True if col_a has the same name as col_b and if the
        subparts are col_a.sub <= col_b.sub.
        """
        
        sz_this = col_a[1]
        sz_that = col_b[1]
        # if column has the same name
        if col_a[0] == col_b[0]:
            # if they both have sub_parts, compare them
            if sz_this and sz_that:
                if sz_this <= sz_that:
                    return True
                else:
                    return False
            # if this index has a sub_part and the other does
            # not, it is potentially redundant
            elif sz_this and sz_that is None:
                return True
            # if neither have sub_parts, it is a match
            elif sz_this is None and sz_that is None:
                return True
        else:
            return False # no longer a duplicate
        
    # Rules for column matching go here.
    def __check_column_list(self, index):
        """Compare the column list of this index with another
        
        index[in]          Instance of Index to compare

        Returns True if column list is a subset of index.
        """
        
        # Uniqueness counts - can't be duplicate if uniquess differs
        if self.unique != index.unique:
            return False
        num_cols_this = len(self.columns)
        num_cols_that = len(index.columns)
        num_cols_same = 0
        if self.type == "BTREE":
            i = 0
            while (i < num_cols_this) and (i < num_cols_that):
                if num_cols_same <= i: # Ensures first N cols are the same
                    if self.__cmp_columns(self.columns[i], index.columns[i]):
                        num_cols_same = num_cols_same + 1
                    else:
                        break
                i = i + 1
        else:  # HASH, RTREE, FULLTEXT
            if (self.type == "FULLTEXT") and (num_cols_this != num_cols_that):
                return False
            i = 0
            while (i < num_cols_this) and (i < num_cols_that):
                if self.__cmp_columns(self.columns[i], index.columns[i]):
                    num_cols_same = num_cols_same + 1
                else:  # Ensures column lists must match
                    num_cols_same = 0
                    break
                i = i + 1
        if (num_cols_same > 0) and (num_cols_this <= num_cols_that):
            return True
        return False
      
    # Rules that apply to all indexes go here.     
    def is_duplicate(self, index):
        """Compare this index with another

        index[in]          Instance of Index to compare

        Returns True if this index is a subset of the Index presented.
        """
        
        # Don't compare the same index - no two indexes can have the same name
        # Don't compare the primary key
        if (self.name == index.name) or (self.name == "PRIMARY"):
            return False
        else:
            return self.__check_column_list(index)
        return False

    def add_column(self, column, sub_part):
        """Add a column to the list of columns for this index

        column[in]         Column to add
        sub_part[in]       Sub part of colunm e.g. a(20)
        """

        col = (column, sub_part)
        if sub_part > 0:
            self.column_subparts = True
        self.columns.append(col)
        
    def get_drop_statement(self):
        """Get the drop statement for this index

        Note: Ignores PRIMARY key indexes.

        Returns the DROP statement for this index.
        """
        
        if self.name == "PRIMARY":
           return None
        query_str = "DROP INDEX %s FROM %s.%s" % (self.name,
                                                  self.db,
                                                  self.table)
        return query_str
    
    def __get_column_list(self):
        """Get the column list for an index
        
        This method is used to print the CREATE and DROP statements
        
        Returns a string representing the list of columns for a
        column list. e.g. 'a, b(10), c'
        """
        
        col_str = ""
        stop = len(self.columns)
        i = 0
        for col in self.columns:
            name, sub_part = (col[0], col[1])
            col_str = col_str + "%s" % (name)
            if sub_part > 0:
                col_str = col_str + "(%d)" % (sub_part)
            i = i + 1
            if (stop > 1) and (i < stop):
                col_str = col_str + ", "
        return col_str
    
    def print_index(self):
        """Print the CREATE INDEX for indexes and ALTER TABLE for a primary key
        """
        
        if self.name == "PRIMARY":
            print "#   ALTER TABLE %s.%s ADD PRIMARY KEY (%s)" % \
                  (self.db, self.table, self.__get_column_list())
        else:
            create_str = "#   CREATE "
            if self.unique:
                create_str += "UNIQUE "
            if self.type == "FULLTEXT":
                create_str += "FULLTEXT "
            create_str += "INDEX %s ON %s.%s (%s) " % \
                  (self.name, self.db, self.table, self.__get_column_list())
            if (self.type == "BTREE") or (self.type == "RTREE"):
                create_str += "USING %s" % (self.type)
            print create_str


class Table:
    """
    The Table class encapsulates a table for a given database. The class
    has the following capabilities:

        - Check to see if the table exists
        - Check indexes for duplicates and redundancies
        - Print list of indexes for the table
    """   
    
    def __init__(self, server1, name, verbose=False):
        """Constructor
        
        server[in]         A Server object
        name[in]           Name of table in the form (db.table)
        verbose[in]        print extra data during operations (optional)
                           default value = False
        """
    
        self.verbose = verbose
        self.server = server1
        self.table = name
        self.db_name, self.tbl_name = _parse_object_name(name)
        self.obj_type = "TABLE"
       
        # We store each type of index in a separate list to make it easier
        # to manipulate
        self.btree_indexes = []
        self.hash_indexes = []
        self.rtree_indexes = []
        self.fulltext_indexes = []
    
    def exists(self, tbl_name=None):
        """Check to see if the table exists
        
        tbl_name[in]       table name (db.table)
                           (optional) If omitted, operation is performed
                           on the class instance table name.

        return True = table exists, False = table does not exist
        """
        
        cur = self.server.cursor()
        db, table = (None, None)
        if tbl_name:
            db, table = _parse_object_name(tbl_name)
        else:
            db = self.db_name
            table = self.tbl_name
        res = cur.execute("SELECT TABLE_NAME " +
                          "FROM INFORMATION_SCHEMA.TABLES " +
                          "WHERE TABLE_SCHEMA = '%s'" % db +
                          " and TABLE_NAME = '%s'" % table)
        cur.close()
        if res:
            return True
        else:
            return False
        
    
    # Put the primary key first so that it can be compared to all indexes
    def __append(self, indexes, index):
        """Encapsulated append() method to ensure the primary key index
        is placed at the front of the list.
        """
        
        if index.name == "PRIMARY":
            indexes.insert(0, index)
        else:
            indexes.append(index)
            
        
    def __check_index(self, index, indexes, master_list):
        """Check a single index for duplicate or redundancy against a list
        of other Indexes.
        
        index[in]          The Index to compare
        indexes[in]        A list of Index instances to compare
        master_list[in]    A list of know duplicate Index instances
        
        Returns a tuple of whether duplicates are found and if found the
        list of duplicate indexes for this table
        """
        
        duplicates_found = False
        duplicate_list = []
        if indexes and index:
            for idx in indexes:
                # Don't compare b == a when a == b has already occurred
                if not index.compared and idx.is_duplicate(index):
                    # make sure we haven't already found this match
                    if not idx.column_subparts:
                        idx.compared = True
                    if not (idx in master_list):
                        duplicates_found = True
                        idx.duplicate_of = index
                        duplicate_list.append(idx)
        return (duplicates_found, duplicate_list)
        
    
    def __check_index_list(self, indexes):
        """Check a list of Index instances for duplicates.
        
        indexes[in]        A list of Index instances to compare
        
        Returns a tuple of whether duplicates are found and if found the
        list of duplicate indexes for this table
        """

        duplicates_found = False
        duplicate_list = []
        # Caller must ensure there are at least 2 elements in the list.
        if len(indexes) < 2:
            return (False, None)
        for index in indexes:
            res = self.__check_index(index, indexes, duplicate_list)
            if res[0]:
                duplicates_found = True
                duplicate_list.extend(res[1])
        return (duplicates_found, duplicate_list)
        
    
    def get_indexes(self):
        """Retrieve the indexes from the server and load them into lists
        based on type.
        
        Returns True - table has indexes, False - table has no indexes
        """

        self.btree_indexes = []
        self.hash_indexes = []
        self.rtree_indexes = []
        self.fulltext_indexes = []

        if self.verbose:
            print "# Getting indexes for %s" % (self.table)
        try:
            rows = self.server.get_tbl_indexes(self.table)
        except MySQLUtilError, e:
            raise e
        
        # Return False if no indexes found.
        if not rows:
            return False
        idx = None
        prev_name = ""
        for row in rows:
            if (row[2] != prev_name) or (prev_name == ""):
                prev_name = row[2]                
                idx = Index(self.db_name, row)
                if idx.type == "BTREE":
                    self.__append(self.btree_indexes, idx)
                elif idx.type == "HASH":
                    self.__append(self.hash_indexes, idx)
                elif idx.type == "RTREE":
                    self.__append(self.rtree_indexes, idx)
                else:
                    self.__append(self.fulltext_indexes, idx)
            elif idx:
                idx.add_column(row[4], row[7])
        return True
    
    
    def check_indexes(self, show_drops=False):
        """Check for duplicate or redundant indexes and display all matches

        show_drops[in]     (optional) If True the DROP statements are printed
       
        Note: You must call get_indexes() prior to calling this method. If
        get_indexes() is not called, no duplicates will be found.
        """
        
        dupes = []
        res = self.__check_index_list(self.btree_indexes)
        # if there are duplicates, add them to the dupes list
        if res[0]:
            dupes.extend(res[1])
        res = self.__check_index_list(self.hash_indexes)
        # if there are duplicates, add them to the dupes list
        if res[0]:
            dupes.extend(res[1])
        res = self.__check_index_list(self.rtree_indexes)
        # if there are duplicates, add them to the dupes list
        if res[0]:
            dupes.extend(res[1])
        # We sort the fulltext index columns - easier to do it once here
        for index in self.fulltext_indexes:
            cols = index.columns
            cols.sort(key=lambda cols:cols[0])
        res = self.__check_index_list(self.fulltext_indexes)
        # if there are duplicates, add them to the dupes list
        if res[0]:
            dupes.extend(res[1])

        if len(dupes) > 0:
            print "# The following indexes are duplicates or redundant " \
                  "for table %s:\n#" % (self.table)
            for index in dupes:
                index.print_index()
                print "#     may be redundant or duplicate of:"
                index.duplicate_of.print_index()
                print "#"
            print "#"
            if show_drops:
                print "#\n# DROP statements:\n#"
                for index in dupes:
                    print "%s;" % (index.get_drop_statement())
                print "#"
        else:
            print "# Table %s has no duplicate indexes.\n#" % (self.table)
    
    
    def __print_index_list(self, indexes):
        """Print the list of indexes
        """
        
        for index in indexes:
            index.print_index()
        
        
    def print_indexes(self):
        """Print all indexes for this table
        """
        
        print "# Showing indexes from %s:\n#" % (self.table)
        self.__print_index_list(self.btree_indexes)
        self.__print_index_list(self.hash_indexes)
        self.__print_index_list(self.rtree_indexes)
        self.__print_index_list(self.fulltext_indexes)
        print "#"

