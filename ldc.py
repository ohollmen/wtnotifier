# LDAP Helper utils for connecting to and searching LDAP.
import ldap
import pprint
import re

uattrs = ["sAMAccountName", "manager", "mail"] # User
mattrs = ["sAMAccountName","mail", 'displayName', 'givenName','sn','name'] # Manager

def tourl(host):
  if not re.search(r'^ldap', host): host = "ldap://" + host
  if not re.search(r'\/$', host): host += "/"
  return host

def ldconnect(ldurl, ldbind=None):
  ldurl = tourl(ldurl)
  ld = ldap.initialize(ldurl)
  #print ("ld" + str(ld))
  if ldbind and ldbind.get("user"):
    ld.simple_bind_s(who=ldbind["user"], cred=ldbind["pass"])
  return ld

# Get search results from LDAP search (listing or single entry)
# Parameters:
# - ld - LDAP Connection
# - lds - LDAP Search definition (with "scope", "base" and "filter")
# KW Params:
# - "ent" - Look for and return single entry (instead of list)
# - "debug" - Output verbose information about search op
# Return 
def ldsearch(ld, lds, **kwargs):
  ats = lds.get("attrs") # or None
  ldfilter = lds.get("filter") or "(objectclass=*)"
  # ldap.SCOPE_BASE
  ldscope = lds["scope"] or ldap.SCOPE_SUBTREE # "sub"
  if kwargs.get('debug'): print("Search by: filter: " + ldfilter + ", scope: " + str(ldscope) + ", base: " + lds["base"]);
  aonly = kwargs.get('attrsonly') or 0
  ldr = ld.search_s(lds["base"], ldscope, filterstr=ldfilter, attrlist=ats, attrsonly=aonly) # [, attrlist=None[, attrsonly=0]]]
  if not ldr: print("No results (for: "+ldfilter+")"); return
  if aonly: print(pprint.pprint(ldr[0]));
  if kwargs.get('debug') > 1: 
    for dn,entry in ldr:
      if not dn: continue
      if not entry: continue
      print('Processing: ',repr(dn))
      #print(json.dumps(entry))
      #print(entry)
      print(pprint.pprint(entry))
  # Force returning single LD entry
  if kwargs.get("ent", False):
    if not ldr[0]: print("No entities in result set"); return None
    if len(ldr) > 1: raise ValueError("Single Entity ( by 'ent') is ambiguous")
    if not ldr[0][0]: print("Inner tuple[0] (DN key) missing"); return
    if not ldr[0][1]: print("Inner tuple[1] (k-v Entry) missing"); return
    #print("Returning single entry:", ldr[0][1]);
    return ldr[0][1]
  return ldr


# Demonstrate ldap (API) scope enumerations from widest to narrowest 
def ldscope_opts():
  print("Scope opts:" + str(ldap.SCOPE_SUBTREE) + ", " + str(ldap.SCOPE_ONE) + ", " + str(ldap.SCOPE_BASE) ) 
  #exit(0)

# Lookup AD Accounts following the organizational info (manager) for all (unique) users in index
# In index Accounts entries should have key "username" to lookup accounts by.
# Implements caching for manager info to not fetch same info twice.
# Kwargs:
# - "sbase" - LDAP Search base for users
#OLDSIGN: def people_ld_lookup(ld, uni_ids, **kwargs): # kattr="_account_id"
def people_ld_lookup(ld, accts_idx, **kwargs):
  #UNUSED: idxkey = kattr
  sbase = kwargs.get("sbase");
  if not sbase: raise ValueError("No sbase for ld user lookups\n")
  midx = {}
  # keys - Gerrit User ID numbers
  for id in accts_idx:
    accts = accts_idx[id]
    lds_self =  {"base": sbase, "scope":ldap.SCOPE_SUBTREE, "filter": "(&(sAMAccountName="+accts["username"]+")(objectClass=person))", "attrs": uattrs}
    u_self = ldsearch(ld, lds_self, debug=0, ent=1); # exit(0);
    if not u_self: print("User '" +accts["username"]+ "' not found"); continue
    if not u_self.get("manager", False): print("User manager info/ref (user:'" +accts["username"]+ "') not found in entry"); continue
    #print(json.dumps(u_self, indent=2));
    # By def. List of tuples u_self[0][1]["manager"]
    
    mdn = u_self["manager"][0]
    if midx.get(mdn): print("Already cached: " + mdn); accts["manager"] = midx.get(mdn); continue
    
    lds_mgr = {"base": mdn, "scope":ldap.SCOPE_BASE, "filter": "(objectClass=person)", "attrs": mattrs}
    
    u_mgr  = ldsearch(ld, lds_mgr, debug=0, ent=1);
    if not u_mgr: print("Manager for User '" +accts["username"]+ "' not found"); continue
    # Mimick "standard" format on manager
    mgr = {"username": u_mgr["sAMAccountName"][0], "email": u_mgr["mail"][0], "name": u_mgr["displayName"][0]}
    midx[mdn] = accts["manager"] = mgr
    #????: accts_idx[accts["username"]] = accts
    #OLD:accts_idx[str(accts["_account_id"])] = accts
    #print(json.dumps(u_mgr, indent=2)); exit(0);
  return accts_idx
