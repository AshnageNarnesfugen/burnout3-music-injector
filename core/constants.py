"""Burnout 3 ISO/RWS knowledge, the original EA Trax track list, and the
audio-pipeline constants shared across the encoder, the workers and the builders."""

# ─── Burnout 3 ISO Knowledge ─────────────────────────────────────────────
KNOWN_DISC_IDS = {
    "SLUS_210.50": "NTSC-U (USA)", "SLES_525.84": "PAL (Europe)",
    "SLES_525.85": "PAL (Europe Alt)", "SLPM_657.19": "NTSC-J (Japan)",
}

ISO_STRUCTURE = {
    "SYSTEM.CNF": "PS2 boot config",
    "SLUS_210.50": "Main executable (NTSC-U)",
    "GLOBAL/": {
        "FRONTEND.TXD": "Menu textures (RenderWare TXD)",
        "GLOBAL.TXD": "Global textures/fonts",
        "VDB.BIN": "Vehicle database (speeds, physics, AI)",
    },
    "TRACKS/": {
        "_EATRAX0.RWS": "🎵 Music container 1 (EA Trax — songs 1-22)",
        "_EATRAX1.RWS": "🎵 Music container 2 (EA Trax — songs 23-44)",
        "TLIST.BIN": "Track names list",
        "[TrackFolders]/": {
            "STATIC.DAT": "Track textures + garage model",
            "STREAMED.DAT": "Track mesh, destructible props, LODs",
            "ENVIRO.DAT": "Skybox, lighting, sun/moon coords",
            "[Track].BGD": "Track config (traffic, spawns, laps, takedowns)",
        },
    },
    "PVEH/": {
        "VLIST.BIN": "Vehicle names list",
        "[Car].BGV": "Vehicle model + textures + deformation + physics",
        "[Car].BTV": "Traffic vehicle variant (identical format to BGV)",
        "[Car].HWD": "Engine sound pitch data",
        "[Car].LWD": "Engine sound samples (PS-ADPCM)",
    },
    "FMV/": {"[Video].PSS": "FMV video files"},
    "SOUNDS/": {"[SFX].RWS": "Sound effects (PS-ADPCM in RWS containers)"},
}

EA_TRAX_SONGS = [
    {"id":1,  "artist":"No Motiv",                     "title":"Independence Day"},
    {"id":2,  "artist":"Amber Pacific",                "title":"Always You"},
    {"id":3,  "artist":"The Ordinary Boys",            "title":"Over The Counter Culture"},
    {"id":4,  "artist":"Funeral For A Friend",         "title":"Rookie Of The Year"},
    {"id":5,  "artist":"Chronic Future",               "title":"Time And Time Again"},
    {"id":6,  "artist":"Franz Ferdinand",              "title":"This Fire"},
    {"id":7,  "artist":"The Von Bondies",              "title":"C'mon C'mon"},
    {"id":8,  "artist":"Ramones",                      "title":"I Wanna Be Sedated"},
    {"id":9,  "artist":"Autopilot Off",                "title":"Make A Sound"},
    {"id":10, "artist":"Ash",                          "title":"Orpheus"},
    {"id":11, "artist":"Yellowcard",                   "title":"Breathing"},
    {"id":12, "artist":"Pennywise",                    "title":"Rise Up"},
    {"id":13, "artist":"Fall Out Boy",                 "title":"Reinventing The Wheel..."},
    {"id":14, "artist":"The F-Ups",                    "title":"Lazy Generation"},
    {"id":15, "artist":"The Lot Six",                  "title":"Autobrats"},
    {"id":16, "artist":"Sahara Hotnights",             "title":"Hot Night Crash"},
    {"id":17, "artist":"Eighteen Visions",             "title":"I Let Go"},
    {"id":18, "artist":"Donots",                       "title":"Saccharine Smile"},
    {"id":19, "artist":"From First To Last",           "title":"Populace In Two"},
    {"id":20, "artist":"Sugarcult",                    "title":"Memory"},
    {"id":21, "artist":"Finger Eleven",                "title":"Stay In Shadow"},
    {"id":22, "artist":"Reggie And The Full Effect",   "title":"Congratulations Smack And Katy"},
    {"id":23, "artist":"Local H",                      "title":"Everyone Alive"},
    {"id":24, "artist":"Maxeen",                       "title":"Please"},
    {"id":25, "artist":"New Found Glory",              "title":"At Least I'm Known For Something"},
    {"id":26, "artist":"My Chemical Romance",          "title":"I'm Not Okay (I Promise)"},
    {"id":27, "artist":"Go Betty Go",                  "title":"C'mon"},
    {"id":28, "artist":"Moments In Grace",             "title":"Broken Promises"},
    {"id":29, "artist":"Midtown",                      "title":"Give It Up"},
    {"id":30, "artist":"1208",                         "title":"Fall Apart"},
    {"id":31, "artist":"Motion City Soundtrack",       "title":"My Favorite Accident"},
    {"id":32, "artist":"Rise Against",                 "title":"Paper Wings"},
    {"id":33, "artist":"The Bouncing Souls",           "title":"Sing Along Forever"},
    {"id":34, "artist":"The Matches",                  "title":"Audio Blood"},
    {"id":35, "artist":"Silent Drive",                 "title":"4/16"},
    {"id":36, "artist":"The Explosion",                "title":"Here I Am"},
    {"id":37, "artist":"The D4",                       "title":"Come On!"},
    {"id":38, "artist":"The Mooney Suzuki",            "title":"Shake That Bush Again"},
    {"id":39, "artist":"Mudmen",                       "title":"Animal"},
    {"id":40, "artist":"The Futureheads",              "title":"Decent Days And Nights"},
    {"id":41, "artist":"Burning Brides",               "title":"Heart Full Of Black"},
    {"id":42, "artist":"Atreyu",                       "title":"Right Side Of The Bed"},
    {"id":43, "artist":"Letter Kills",                 "title":"Radio Up"},
    {"id":44, "artist":"Jimmy Eat World",              "title":"Just Tonight..."},
]

AUDIO_EXTENSIONS = {
    ".mp3",".flac",".ogg",".wav",".aac",".m4a",".wma",".opus",
    ".aiff",".aif",".ape",".wv",".tta",".ac3",".mka",".mpc",".shn",
}

RWS_AUDIO_CONTAINER = 0x0000080D
RWS_AUDIO_HEADER = 0x0000080E
RWS_AUDIO_DATA = 0x0000080F


# ─── Audio processing chain (shared by both encode passes) ───────────────
# Resample to 32 kHz with high-precision soxr, then a gentle 15.5 kHz lowpass
# (just under the 16 kHz Nyquist). 15.5 kHz keeps the brightness the old
# 14 kHz cutoff was throwing away while still taming aliasing.
AUDIO_RESAMPLE_FILTER = "aresample=resampler=soxr:precision=28,lowpass=f=15500"

# Loudness target. EA Trax masters are very hot, so custom music must be brought
# up to a comparable level or it sounds weak next to the original soundtrack and
# the engine SFX. Two-pass loudnorm (measure, then apply a linear gain) at
# ~-10 LUFS / -1 dBFS true peak matches the game without pumping artifacts.
LOUDNORM_TARGET = "I=-10:TP=-1.0:LRA=11"
