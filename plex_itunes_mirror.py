#!/usr/bin/python

import subprocess
import sys
import os
from pipes import quote
import plistlib
import urlparse
import urllib
import urllib2
import sqlite3
import datetime
import shutil
from xml.dom import minidom

HOST="Your-Mac.local"
PLEX_HOST = "http://localhost:32400"
PLEX_LIBRARY_DB_FILE = "/var/lib/plexmediaserver/Library/Application Support/Plex Media Server/Plug-in Support/Databases/com.plexapp.plugins.library.db"
REMOTEFILE = "/Users/yourmacusername/Music/iTunes/iTunes Music Library.xml"
### Change this if you want to add your itunes rating each track in plex
UPDATE_PLEX_RATING = False

#### Get XML data
itunes_xml_cmd = "cat %s" % quote(REMOTEFILE)
output, error = subprocess.Popen(["ssh", "%s" % HOST, itunes_xml_cmd],
                       shell=False,
                       stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE).communicate()
            
if error != "":
    print >>sys.stderr, "ERROR: %s" % error
    sys.exit(0)

itunes_library = plistlib.readPlistFromString(output)


#### PLEX PLAYLIST FUNCTIONS


def parsePlaylistXml(string):
    _playlists = []
    int_keys = ['ratingKey']
    xmldoc = minidom.parseString(string)
    playlist_el = xmldoc.getElementsByTagName('Playlist')
    for p in playlist_el :
        data = {}
        for key in p.attributes.keys():
            val = p.attributes.get(key).value
            if key in int_keys:
                val = int(val)
            data[key] = val
        _playlists.append(data)
        
    return _playlists

def parsePlaylistItemsXml(string):
    _items = []
    int_keys = ['ratingKey','parentRatingKey','playlistItemID']
    xmldoc = minidom.parseString(string)
    items_el = xmldoc.getElementsByTagName('Track')
    for t in items_el :
        data = {}
        for key in t.attributes.keys():
            val = t.attributes.get(key).value
            if key in int_keys:
                val = int(val)
            data[key] = val
        _items.append(data)
        
    return _items


def getPlaylists():
    response = urllib2.urlopen("%s/playlists/all" % PLEX_HOST)
    return parsePlaylistXml(response.read())

def getPlaylist(playlist_id):
    response = urllib2.urlopen("%s/playlists/%d" % (PLEX_HOST,playlist_id))
    return parsePlaylistItemsXml(response.read())
    
def addPlaylist(name):
    params = {
        "type": "audio",
        "title": name,
        "smart": "0",
        "playQueueID" : "0"
    }
    data = urllib.urlencode(params)
    opener = urllib2.build_opener(urllib2.HTTPHandler)
    request = urllib2.Request("%s/playlists?%s" % (PLEX_HOST,data))
    request.add_data("")
    response = opener.open(request)
    playlists = parsePlaylistXml(response.read())
    
    print "Added playlist: %s" % name
    
    for p in playlists:
        return  p
    return None


def deletePlaylist(playlist_id):
    opener = urllib2.build_opener(urllib2.HTTPHandler)
    request = urllib2.Request("%s/playlists/%d" % (PLEX_HOST,playlist_id), data='')
    request.get_method = lambda: 'DELETE'
    response = opener.open(request)
    return response.read()

def deletePlaylistItem(playlist_id, playlist_item_id):
    opener = urllib2.build_opener(urllib2.HTTPHandler)
    request = urllib2.Request("%s/playlists/%d/items/%d" % (PLEX_HOST,playlist_id,playlist_item_id), data='')
    request.get_method = lambda: 'DELETE'
    response = opener.open(request)
    playlists = parsePlaylistXml(response.read())
    for p in playlists:
        return  p
    return None


def addSongToPlaylist(playlist_id,metadata_id,library_section_uuid):
    opener = urllib2.build_opener(urllib2.HTTPHandler)
    uri_param = urllib.quote("library://%s/item//library/metadata/%s" % (library_section_uuid, metadata_id))
    
    request = urllib2.Request("%s/playlists/%d/items?uri=%s" % (PLEX_HOST,playlist_id,uri_param), data='')
    request.get_method = lambda: 'PUT'
    response = opener.open(request)
    playlists = parsePlaylistXml(response.read())
    for p in playlists:
        return  p
    return None

def setTrackRating(metadata_id, rating):
    opener = urllib2.build_opener(urllib2.HTTPHandler)
    request = urllib2.Request("%s/library/metadata/%d?rating=%d" % (PLEX_HOST,metadata_id,rating), data='')
    request.get_method = lambda: 'PUT'
    response = opener.open(request)
    print "Set rating %d for metadata %d" % (metadata_id,rating)
    


#copy plex dir to tmp just to read
plex_tmp_file = os.path.join("/", "tmp","plex.tmp.db")
shutil.copyfile(PLEX_LIBRARY_DB_FILE ,plex_tmp_file )

plex_db_connection = sqlite3.connect(plex_tmp_file)
plex_db = plex_db_connection.cursor()

def searchPlexForFilename(filename):
    t = ("%%%s" % filename,)
    plex_db.execute("""
        SELECT metadata_items.id, library_sections.uuid
        FROM media_parts
        INNER JOIN media_items
            ON media_parts.media_item_id = media_items.id
        INNER JOIN metadata_items
            ON media_items.metadata_item_id = metadata_items.id
        INNER JOIN library_sections
            ON metadata_items.library_section_id = library_sections.id
        WHERE library_sections.uuid IS NOT NULL
            AND metadata_items.id IS NOT NULL
            AND media_parts.file LIKE ?""", t)
    return plex_db.fetchone()
    

def getLocalFilename(xml_filename):
    replaced_filename = xml_filename.replace(itunes_library['Music Folder'], "file://localhost/")
    replaced_filename = unicode(urlparse.unquote(urlparse.urlparse(replaced_filename).path[1:]),"utf8")
    return replaced_filename


SONG_DATA = {}
IGNORE_KEYS = ['Master','Distinguished Kind']

existing_plex_playlists = getPlaylists()


for trackid,attributes in itunes_library['Tracks'].iteritems():
    song = attributes
    
    if UPDATE_PLEX_RATING and 'Rating' in song.keys():
        song_filename = getLocalFilename(song['Location'])
        result = searchPlexForFilename(song_filename)
        
        if result != None:
            metadata_id, section_uuid = result
            rating = int(song['Rating'] / 10)
            
            setTrackRating(metadata_id,rating)
        
    
    SONG_DATA[int(trackid)] = song

def shouldCopyPlaylist(playlist):
    
    if 'Playlist Items' not in playlist:
        return False
    
    for k in IGNORE_KEYS:
        if k in playlist.keys():
            return False
    
    return True


for playlist in itunes_library['Playlists']:
    
    if not shouldCopyPlaylist(playlist):
        continue
    
    plex_playlist = None
    
    for p in existing_plex_playlists:
        if playlist['Name'] == p['title']:
            #tracks = getPlaylist(p['ratingKey'])
            #if tracks != None:
            #    for t in tracks:
            #        deletePlaylistItem(p['ratingKey'],t['playlistItemID'])
            plex_playlist = p
            break
    
    if plex_playlist == None:
        plex_playlist = addPlaylist(playlist['Name'])
    
    if plex_playlist == None:
        continue
    
    
    print "################"
    print "Adding playlist: %s" % plex_playlist['title']
    print "################"
     
    plex_playlist_id = plex_playlist['ratingKey']
    
    for track in playlist['Playlist Items']:
        trackid=int(track['Track ID'])
        song = SONG_DATA[trackid]
        
        song_filename = getLocalFilename(song['Location'])
        result = searchPlexForFilename(song_filename)
        
        if result == None:
            print "Could not find track: %s by %s in plex db" % (song['Name'], song['Artist'])
            continue
            
        metadata_id, section_uuid = result
        
        playlist_result = addSongToPlaylist(plex_playlist_id,metadata_id, section_uuid)
        if playlist_result != None:
            print "Added %s by %s to playlist: %s" % (song['Name'], song['Artist'], plex_playlist['title'])
        

plex_db_connection.close()
os.remove(plex_tmp_file)
sys.exit(0)
