import json
import ldc
import time
import requests
import dateutil.parser
import re
import netrc
import os

# import gerrit_open_notify

def loadjson(fn):
  jstr = open(fn, "rb").read();
  return json.loads(jstr)

def loadconfigs(typelbl, **kwargs):
  cfg = loadjson("./"+typelbl+".conf.json")
  cfg2 = loadjson("./sysenv.conf.json")
  initconfig(cfg, cfg2);
  if kwargs.get("create"): return create(cfg) # Instantiate ...
  return cfg # Plain (combined) config

# Blend global and system config
def initconfig(cfg, sysenv):
  cfg["sysenv"] = sysenv

# Factory for creating runtime instance based on cfg.systype
def create(cfg):
  ss = None
  if cfg["systype"] == "gerrit": ss = gerritsys(cfg);
  elif cfg["systype"] == "jira": ss = jirasys(cfg);
  return ss

# Generic netrc based credentials retrieval
def getcreds(host, **kwargs):
  # os.environ['GUSER'] = os.environ['USER']
  user, _, password = netrc.netrc().authenticators(host)
  # Optional Overrides from environment
  if kwargs.get("envkeys"):
    kv = kwargs.get("envkeys")
    #if len(kw) != 2: print("");exit(0);
    if os.environ.get(kv[0]): user = os.environ.get(kv[0])
    if os.environ.get(kv[1]): password = os.environ.get(kv[1])
  user = re.sub(r"\+", " ", user)
  if kwargs.get("debug"): print("machine:" + host + ", user:" + user);
  #exit(0)
  creds = {"user": user, "pass": password}
  # Turn creds directly into requests supported auth object
  if kwargs.get("http"): return requests.auth.HTTPDigestAuth(creds['user'], creds['pass'])
  #elif kwargs.get("jira"): return ...
  return creds

# Base class for specific Work task sources.
# Holds/Contains the LDAP Config time filtering info.
class wtsys(object):
  uattrs = ["sAMAccountName", "manager", "mail"] # User
  mattrs = ["sAMAccountName","mail", 'displayName', 'givenName','sn','name'] # Manager
  sbase = None
  now = int(time.time())
  age_days = 14
  limage = 86400 * age_days
  def __init__(self, conf):
    systype = conf.get("systype", "")
    oksys = {"gerrit": 1, "jira": 1}
    if (not systype) or (not oksys[systype]): raise ValueError(systype)
    #print("wtsys Config: "+ json.dumps(conf));
    ldconf = conf["sysenv"]
    self.ld = ldc.ldconnect(ldconf["ldaphost"], ldbind={"user": ldconf["user"], "pass": ldconf["pass"]})
    wtsys.sbase = ldconf.get("sbase")
    if not wtsys.sbase: raise ValueError("Missing User searchbase !");
    # Pick up time constraints
    if conf.get("age_days", 0): self.settime(age_days=conf["age_days"])
    if conf.get("now", 0): self.settime(age_days=conf["now"]) # For testing
    #if systype == "gerrit": gerritsys.__init__(self, conf)
    #elif systype == "jira": jirasys.__init__(self, conf)

  #def filterents(self):
  #  print("Filtering in base ...by: ...");
  #  pass
  #@staticmethod
  @classmethod
  def settime(cls, **kwargs):
    #print("Calling class method ...");
    if kwargs.get('age_days'): cls.age_days = kwargs.get('age_days')
    if kwargs.get('now'): cls.now = kwargs.get('now')
    limage = 86400 * cls.age_days
    #print("Set: age_days: " + str(cls.age_days) + " now: " + str(cls.now));
  # Generate filter callback
  def genfilter(attr):
    # Q: Do we need this if we always look into class vars ?
    # A: Yes, because callback nature functio (i.e. filter) could only be staticmethod
    # or fully procedural function, which then does not get access to class vars !
    def myfilter(): return 1 
    return myfilter
    

class gerritsys(wtsys):
  burl = None # "/a/"
  ishttp = 1
  @staticmethod
  def tobaseurl(host):
    # /a/ for gerrit denotes authenticated API URL
    return "http://" + host + "/a/"
  def __init__(self, conf):
    #print("Constructing Gerrit!" + str(wtsys));
    if not conf: raise ValueError("No Config for gerritsys !")
    if conf["host"]: gerritsys.burl = gerritsys.tobaseurl(conf["host"])
    #OLDTEST(OK):print(wtsys.uattrs);
    # TypeError: must be type, not instance
    #super(type(gerritsys)).__init__(self)
    # ALT to calling 
    wtsys.__init__(self, conf)
    #OK:print("Set burl in class to: " + gerritsys.burl);
  # Get Google/Gerrit API REST Response
  @staticmethod
  def http_gjson(url, **kwargs):
    if kwargs.get("auth") == None:
      print("Did not get AUTH for Gerrit API Call !");
      return None
    r = requests.get(gerritsys.burl+ url, auth=kwargs.get("auth"))
    if kwargs.get('debug', False):
      print("Content(DEBUG):" + r.text)
    # Strip out: )]}'
    jtext = r.text.replace(')]}\'', '')
    #print("Content:" + jtext)
    changes = None
    try:
      changes = json.loads(jtext, encoding='utf-8')
    except ValueError as err:
      print("Content: " + jtext);
      #print("Failed to parse JSON: {0}".format(err) ); return None; # sys.exc_info()[0]
      print("Failed to parse JSON:", err ); return None;
    return changes
  # Process changes to index unique user ID:s
  # Gather e["owner"]["_account_id"] to dummy 1 valued dict
  @staticmethod
  def change_user_idx(changes):
    uni_ids_idx = {}
    for e in changes:
      # id = e.get(e["owner"]["_account_id"], 0)
      if not e["owner"]: continue
      id = e["owner"]["_account_id"]
      if not id: print("Change: No id for user"); continue
      if uni_ids_idx.get(str(id), ""): uni_ids_idx[id] += 1 # pass
      else: uni_ids_idx[id] = 1
    return uni_ids_idx
  # Resolve user's account from source system
  @staticmethod
  def gerrit_user_lookup(uni_ids, **kwargs):
    accts_idx = {}
    auth = kwargs.get("auth", None)
    if not auth: raise ValueError("No auth passed !")
    for id in uni_ids:
      accts = gerritsys.http_gjson('accounts/'+str(id)+'/detail', auth=auth, debug=0)
      if accts == None: raise ValueError("No Account Results by:" + str(id))
      accts_idx[str(accts["_account_id"])] = accts
    return accts_idx
  # Gerrit ents search
  def apisearch(self, **kwargs):
    auth = kwargs.get("auth")
    if not auth: raise ValueError("No auth for gerrit api search!")
    changes = gerritsys.http_gjson('changes/?q=status:open&n=1500', auth=auth)
    if changes == None: raise ValueError("No Gerrit changes !")
    for it in changes:
      it["wtid"] = str(it["_number"])
      it["userkey"] = str(it["owner"]["_account_id"])
    # Find unique user id:s and index
    uni_ids_idx = gerritsys.change_user_idx(changes)
    #if debug: print(json.dumps(uni_ids_idx))
    uni_ids = uni_ids_idx.keys()
    #if debug: print(json.dumps(uni_ids))
    # TODO: Do initial people lookup from gerrit
    accts_idx = gerritsys.gerrit_user_lookup(uni_ids, auth=auth)
    ldc.people_ld_lookup(self.ld, accts_idx, sbase=self.sbase)
    # print(json.dumps(accts_idx, indent=2)); exit(0)
    self.accts_idx = accts_idx
    return changes
  
  @staticmethod
  def timefilter(ch):
    chdt = dateutil.parser.parse(ch["updated"]+'Z') # "created"
    # NOT: chtime = chdt.total_seconds() # chdt.time() is Effectively datetime.time() on instance
    chtime = time.mktime(chdt.timetuple()) # Need to Adjust to UTC ? Option1 - add Z to timestamp
    age = wtsys.now - chtime # s.
    #timestamp1 = calendar.timegm(chdt.timetuple())
    #NOT: chtime = datetime.datetime.utcfromtimestamp(timestamp1) # Created datetime
    #age = now - timestamp1
    ch["age_s"] = age # Add Age
    ch["age_d"] = ch["age_s"] / 86400
    inc = 0
    if age > wtsys.limage: inc = 1
    #if debug > 1: dumptimes(ch, chtime, age, inc)
    return inc
######################################################################################
class jirasys(wtsys):
  ishttp = 0
  #@staticmethod
  def tourl(self, host):
    prefix = "http://"
    print(json.dumps(self.__dict__));
    if self.secure: prefix = "https://"
    return prefix+host # +"/"
  def __init__(self, conf):
    import jira
    self.type = ""
    self.jql = conf.get('filter')
    #print(json.dumps(conf));
    # TODO: Probe secure
    if conf.get("secure", None): self.secure = 1
    url = self.tourl(conf.get('host'))
    print("Will connect to: " + url);
    self.ji = jira.JIRA(url, basic_auth=(conf['user'], conf['pass']))
    wtsys.__init__(self, conf)
  def apisearch(self, **dummy):
    #fields = ["assignee","summary","description"] # AttributeError: 'list' object has no attribute 'copy' ... TypeError: 'tuple' object does not support item assignment
    fields = "assignee, summary, description, created, updated"
    jql = self.jql
    jql = re.sub('\+', ' ', jql);
    # Error in the JQL Query: The character '%' is a reserved JQL character.
    # '%' = %25
    # https://github.com/pycontribs/jira/issues/336
    print("Querying by: '" + jql + "'");
    j = self.ji.search_issues(jql_str=jql, json_result=True, maxResults=1000, fields=fields) # fields="key, attachment"
    issues = j["issues"];
    #return issues
    ucache = {}
    def getuser(entf):
      assi = entf["assignee"]
      if ucache.get(assi["name"]): print("Already cached:" + assi["name"]); return
      ue = {}
      ue["username"]= assi["name"] # Username.
      ue["name"]    = assi["displayName"] # Users full name should be in in "name"
      ue["email"]   = assi["emailAddress"]
      ucache[assi["name"]] = ue
      
    # See: customfield_11002, customfield_11401, creator, reporter, created, updated (2020-02-03T14:46:38.000-0800)
    ilist = []
    # TODO: Decide if we should stick w. universal naming OR let a (callback and) template handle it
    for ent in issues:
      ne = {}
      ne["wtid"] = ent["key"] # Ticket ID
      f = ent["fields"]
      ne["userkey"] = ne["username"]= f["assignee"]["name"] # Username.
      getuser(f)
      #ne["name"]    = f["assignee"]["displayName"] # Users full name should be in in "name"
      #ne["email"]   = f["assignee"]["emailAddress"]
      ne["subject"] = f["summary"] # subject in Gerrit (jira "description" is much longer)
      ne["created"] = f["created"]
      ne["updated"] = f["updated"]
      ilist.append(ne);
    # Process userindex ?
    
    #print("Search from: "+ self.sbase);
    ldc.people_ld_lookup(self.ld, ucache, sbase=self.sbase) # accts_idx
    self.accts_idx = ucache
    #print(json.dumps(ucache, indent=2)); exit(0)
    return ilist
  @staticmethod
  # The native JIRA Attr is: "created"/"updated" and Format is: 2016-12-11T08:23:53.000-0800
  def timefilter(ch):
    chdt = dateutil.parser.parse(ch["updated"]) # "created"
    # NOT: chtime = chdt.total_seconds() # chdt.time() is Effectively datetime.time() on instance
    chtime = time.mktime(chdt.timetuple()) # Need to Adjust to UTC ? Option1 - add Z to timestamp
    age = wtsys.now - chtime # s.
    #timestamp1 = calendar.timegm(chdt.timetuple())
    #NOT: chtime = datetime.datetime.utcfromtimestamp(timestamp1) # Created datetime
    #age = now - timestamp1
    ch["age_s"] = age # Add Age
    ch["age_d"] = ch["age_s"] / 86400
    inc = 0
    if age > wtsys.limage: inc = 1
    #if debug > 1: dumptimes(ch, chtime, age, inc)
    return inc
