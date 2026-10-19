#!/usr/bin/env python3
"""Generate tracemap/assets/city_codes.json (airport/city codes used in router hostnames).

City-level coordinates, rounded. Source: general knowledge of well-known internet hub cities;
this is a small hand-made table, not an authoritative gazetteer. Run: python tools/make_city_codes.py
"""
import json
from pathlib import Path

# code, city, country, lat, lon, extra name aliases (lowercase, no spaces)
ROWS = [
 # North America
 ("iad","Ashburn","United States",39.04,-77.49,["ashburn","washington","washingtondc","dca","wdc","asbnva"]),
 ("jfk","New York","United States",40.71,-74.01,["newyork","nyc","newark","ewr","nyk","nycmny"]),
 ("lax","Los Angeles","United States",34.05,-118.24,["losangeles","la","lsanca"]),
 ("sjc","San Jose","United States",37.34,-121.89,["sanjose","paloalto","pao","snjsca"]),
 ("sfo","San Francisco","United States",37.77,-122.42,["sanfrancisco","snfcca"]),
 ("ord","Chicago","United States",41.88,-87.63,["chicago","chi","chcgil"]),
 ("dfw","Dallas","United States",32.78,-96.80,["dallas","dllstx"]),
 ("atl","Atlanta","United States",33.75,-84.39,["atlanta","atlnga"]),
 ("mia","Miami","United States",25.76,-80.19,["miami","miamfl"]),
 ("sea","Seattle","United States",47.61,-122.33,["seattle","sttlwa"]),
 ("den","Denver","United States",39.74,-104.99,["denver"]),
 ("bos","Boston","United States",42.36,-71.06,["boston"]),
 ("phx","Phoenix","United States",33.45,-112.07,["phoenix"]),
 ("iah","Houston","United States",29.76,-95.37,["houston","hou"]),
 ("msp","Minneapolis","United States",44.98,-93.27,["minneapolis"]),
 ("slc","Salt Lake City","United States",40.76,-111.89,["saltlakecity"]),
 ("las","Las Vegas","United States",36.17,-115.14,["lasvegas"]),
 ("pdx","Portland","United States",45.52,-122.68,["portland"]),
 ("yyz","Toronto","Canada",43.65,-79.38,["toronto","tor"]),
 ("yul","Montreal","Canada",45.50,-73.57,["montreal","mtl"]),
 ("yvr","Vancouver","Canada",49.28,-123.12,["vancouver"]),
 ("mex","Mexico City","Mexico",19.43,-99.13,["mexicocity"]),
 # Europe
 ("lhr","London","United Kingdom",51.51,-0.13,["london","lon","ldn","londen"]),
 ("man","Manchester","United Kingdom",53.48,-2.24,["manchester"]),
 ("dub","Dublin","Ireland",53.35,-6.26,["dublin"]),
 ("fra","Frankfurt","Germany",50.11,8.68,["frankfurt","ffm","frnkge"]),
 ("ber","Berlin","Germany",52.52,13.40,["berlin"]),
 ("muc","Munich","Germany",48.14,11.58,["munich"]),
 ("dus","Dusseldorf","Germany",51.23,6.77,["dusseldorf"]),
 ("ham","Hamburg","Germany",53.55,9.99,["hamburg"]),
 ("ams","Amsterdam","Netherlands",52.37,4.90,["amsterdam","amstnl"]),
 ("cdg","Paris","France",48.86,2.35,["paris","par"]),
 ("mrs","Marseille","France",43.30,5.37,["marseille"]),
 ("mad","Madrid","Spain",40.42,-3.70,["madrid"]),
 ("bcn","Barcelona","Spain",41.39,2.17,["barcelona"]),
 ("lis","Lisbon","Portugal",38.72,-9.14,["lisbon"]),
 ("mxp","Milan","Italy",45.46,9.19,["milan","mil"]),
 ("fco","Rome","Italy",41.90,12.50,["rome"]),
 ("zrh","Zurich","Switzerland",47.38,8.54,["zurich"]),
 ("gva","Geneva","Switzerland",46.20,6.14,["geneva"]),
 ("vie","Vienna","Austria",48.21,16.37,["vienna"]),
 ("prg","Prague","Czechia",50.08,14.44,["prague"]),
 ("waw","Warsaw","Poland",52.23,21.01,["warsaw"]),
 ("bud","Budapest","Hungary",47.50,19.04,["budapest"]),
 ("otp","Bucharest","Romania",44.43,26.10,["bucharest"]),
 ("sof","Sofia","Bulgaria",42.70,23.32,["sofia"]),
 ("ath","Athens","Greece",37.98,23.73,["athens"]),
 ("arn","Stockholm","Sweden",59.33,18.07,["stockholm","sto"]),
 ("cph","Copenhagen","Denmark",55.68,12.57,["copenhagen"]),
 ("osl","Oslo","Norway",59.91,10.75,["oslo"]),
 ("hel","Helsinki","Finland",60.17,24.94,["helsinki"]),
 ("svo","Moscow","Russia",55.76,37.62,["moscow","mow"]),
 ("ist","Istanbul","Turkey",41.01,28.98,["istanbul"]),
 # Middle East / Africa
 ("dxb","Dubai","United Arab Emirates",25.20,55.27,["dubai"]),
 ("auh","Abu Dhabi","United Arab Emirates",24.45,54.38,["abudhabi"]),
 ("fjr","Fujairah","United Arab Emirates",25.12,56.33,["fujairah"]),
 ("doh","Doha","Qatar",25.29,51.53,["doha"]),
 ("bah","Manama","Bahrain",26.23,50.59,["manama","bahrain"]),
 ("ruh","Riyadh","Saudi Arabia",24.71,46.68,["riyadh"]),
 ("jed","Jeddah","Saudi Arabia",21.54,39.17,["jeddah"]),
 ("tlv","Tel Aviv","Israel",32.08,34.78,["telaviv"]),
 ("cai","Cairo","Egypt",30.04,31.24,["cairo"]),
 ("jnb","Johannesburg","South Africa",-26.20,28.05,["johannesburg","jhb"]),
 ("cpt","Cape Town","South Africa",-33.92,18.42,["capetown"]),
 ("los","Lagos","Nigeria",6.52,3.38,["lagos"]),
 ("nbo","Nairobi","Kenya",-1.29,36.82,["nairobi"]),
 ("mba","Mombasa","Kenya",-4.04,39.67,["mombasa"]),
 # Asia
 ("bom","Mumbai","India",19.08,72.88,["mumbai","bombay"]),
 ("maa","Chennai","India",13.08,80.27,["chennai","madras"]),
 ("blr","Bengaluru","India",12.97,77.59,["bengaluru","bangalore"]),
 ("del","Delhi","India",28.61,77.21,["delhi","newdelhi"]),
 ("hyd","Hyderabad","India",17.39,78.49,["hyderabad"]),
 ("ccu","Kolkata","India",22.57,88.36,["kolkata","calcutta"]),
 ("khi","Karachi","Pakistan",24.86,67.00,["karachi"]),
 ("cmb","Colombo","Sri Lanka",6.93,79.86,["colombo"]),
 ("dac","Dhaka","Bangladesh",23.81,90.41,["dhaka"]),
 ("sin","Singapore","Singapore",1.35,103.82,["singapore","sg","sngpsi"]),
 ("kul","Kuala Lumpur","Malaysia",3.14,101.69,["kualalumpur"]),
 ("cgk","Jakarta","Indonesia",-6.21,106.85,["jakarta"]),
 ("bkk","Bangkok","Thailand",13.76,100.50,["bangkok"]),
 ("sgn","Ho Chi Minh City","Vietnam",10.82,106.63,["hochiminh","saigon"]),
 ("han","Hanoi","Vietnam",21.03,105.85,["hanoi"]),
 ("mnl","Manila","Philippines",14.60,120.98,["manila"]),
 ("hkg","Hong Kong","Hong Kong",22.32,114.17,["hongkong","hk","hnkgch"]),
 ("tpe","Taipei","Taiwan",25.03,121.57,["taipei"]),
 ("pek","Beijing","China",39.90,116.41,["beijing"]),
 ("pvg","Shanghai","China",31.23,121.47,["shanghai","sha"]),
 ("can","Guangzhou","China",23.13,113.26,["guangzhou"]),
 ("icn","Seoul","South Korea",37.57,126.98,["seoul"]),
 ("pus","Busan","South Korea",35.18,129.08,["busan"]),
 ("nrt","Tokyo","Japan",35.68,139.69,["tokyo","tyo","tokyjp"]),
 ("kix","Osaka","Japan",34.69,135.50,["osaka"]),
 # Oceania / South America
 ("syd","Sydney","Australia",-33.87,151.21,["sydney"]),
 ("mel","Melbourne","Australia",-37.81,144.96,["melbourne"]),
 ("per","Perth","Australia",-31.95,115.86,["perth"]),
 ("bne","Brisbane","Australia",-27.47,153.03,["brisbane"]),
 ("akl","Auckland","New Zealand",-36.85,174.76,["auckland"]),
 ("gru","Sao Paulo","Brazil",-23.55,-46.63,["saopaulo","spo"]),
 ("gig","Rio de Janeiro","Brazil",-22.91,-43.17,["riodejaneiro","rio"]),
 ("eze","Buenos Aires","Argentina",-34.60,-58.38,["buenosaires"]),
 ("scl","Santiago","Chile",-33.45,-70.67,["santiago"]),
 ("bog","Bogota","Colombia",4.71,-74.07,["bogota"]),
 ("lim","Lima","Peru",-12.05,-77.04,["lima"]),
]

# Three-letter codes that are also everyday router vocabulary. They are only trusted when the
# label ends in a digit (for example "lax1"), never when they stand alone.
out = {"codes": {}, "names": {}}
for code, city, country, lat, lon, aliases in ROWS:
    out["codes"][code] = [city, country, lat, lon]
    for a in aliases + [city.lower().replace(" ", "")]:
        if len(a) >= 4:
            out["names"][a] = code
        elif len(a) == 3 and a not in out["codes"]:
            out["codes"][a] = [city, country, lat, lon]
Path(__file__).resolve().parent.parent.joinpath("tracemap/assets/city_codes.json").write_text(
    json.dumps(out, indent=0, ensure_ascii=False))
print(len(out["codes"]), "codes,", len(out["names"]), "names")
